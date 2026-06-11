"""
BuyWise Agent MVP — LangGraph workflow (warranty/return only).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from agent.state import BuyWiseState, EvidenceChunk
from agent.agents.supervisor import run_supervisor
from agent.agents.order_agent import run_order_agent
from agent.agents.policy_agent import run_policy_agent
from agent.agents.verifier_agent import run_verifier
from agent.agents.action_agent import run_action_agent
from retrieval import HybridRetrievalPipeline, SimpleRetriever


# ── Shared retriever (index once, search many) ────────────────────────────

_RETRIEVER: SimpleRetriever | None = None


def _get_retriever() -> SimpleRetriever:
    """Singleton retriever – we load sample data once."""
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = SimpleRetriever()
    return _RETRIEVER


def _load_sample_data(source_ids: list[str]) -> list[EvidenceChunk]:
    """Parse sample-data source dirs (or standalone files) into EvidenceChunks."""
    from ingestion.parsers.pdf_parser import parse_pdf
    from ingestion.parsers.csv_parser import parse_csv
    from ingestion.parsers.email_parser import parse_eml
    from ingestion.parsers.html_parser import parse_html

    all_chunks: list[EvidenceChunk] = []
    seen: set[str] = set()

    for sid in source_ids:
        p = Path(sid).resolve()
        if not p.exists():
            continue
        if p.is_dir():
            for child in sorted(p.iterdir()):
                all_chunks.extend(_parse_one_file(str(child.absolute()), seen))
        else:
            all_chunks.extend(_parse_one_file(str(p), seen))

    return all_chunks


def _parse_one_file(path: str, seen: set[str]) -> list[EvidenceChunk]:
    """Parse a single file, skip duplicates via file-hash tracking."""
    from agent.state import hash_content

    p = Path(path)
    if not p.is_file():
        return []

    raw = p.read_bytes()
    fh = hash_content(raw)
    if fh in seen:
        return []
    seen.add(fh)

    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            src, chunks = parse_pdf(path)
        elif ext == ".csv":
            src, chunks, _ = parse_csv(path)
        elif ext == ".eml":
            src, chunks = parse_eml(path)
        elif ext in (".html", ".htm"):
            src, chunks = parse_html(path)
        elif ext == ".txt":
            # Treat .txt as a simple text source
            from datetime import datetime
            from agent.state import SourceDocument, DocType, make_chunk_id

            name = p.stem.lower()
            doc_type = DocType.RECEIPT if "receipt" in name else DocType.WARRANTY if "warranty" in name else DocType.MANUAL
            src = SourceDocument(
                source_id=f"src_{fh[:12]}",
                user_id="default",
                file_hash=fh,
                doc_type=doc_type,
                title=p.name,
                created_at=datetime.fromtimestamp(p.stat().st_mtime),
                metadata={"file_path": path},
            )
            text = raw.decode("utf-8", errors="replace")
            paras = [x.strip() for x in text.split("\n\n") if x.strip()]
            chunks = [
                EvidenceChunk(
                    chunk_id=make_chunk_id(src.source_id, None, None, i),
                    source_id=src.source_id,
                    text=para[:2000],
                    metadata={"doc_type": doc_type.value},
                )
                for i, para in enumerate(paras)
            ]
        else:
            return []
    except Exception:
        return []

    for c in chunks:
        c.trust_score = 0.9 if "warranty" in c.metadata.get("doc_type", "") else 0.8
    return chunks


# ── Graph Nodes ─────────────────────────────────────────────────────────────

def classify_intent_node(state: dict) -> dict:
    """Node 1 – classify intent (only warranty/return matters for MVP)."""
    return run_supervisor(state)


def ingest_and_index_node(state: dict) -> dict:
    """Node 2 – parse sample files and index into retriever."""
    source_ids = state.get("uploaded_source_ids", [])
    if not source_ids:
        return {**state, "retrieval_attempts": state.get("retrieval_attempts", 0) + 1}

    chunks = _load_sample_data(source_ids)
    retriever = _get_retriever()
    retriever.index_chunks(chunks)

    return {
        **state,
        "retrieval_attempts": state.get("retrieval_attempts", 0) + 1,
        "_indexed_chunks": len(chunks),
    }


def retrieve_evidence_node(state: dict) -> dict:
    """Node 3 – retrieve evidence relevant to the user query."""
    query = state.get("user_query", "")
    intent = state.get("intent", "")
    retriever = _get_retriever()

    pipeline = HybridRetrievalPipeline(retriever)

    # Primary search: keyword-relevant chunks
    result = pipeline.retrieve(query=query, top_k=10, max_chunks=5)

    # Fallback: if the retriever has data but keyword search missed some
    # doc_types, pull one chunk from each underrepresented type so
    # every agent gets something to work with.
    seen_types = {c.metadata.get("doc_type") for c in result["chunks"]}
    all_chunks = retriever._chunks if hasattr(retriever, "_chunks") else []
    for c in all_chunks:
        dt = c.metadata.get("doc_type")
        if dt and dt not in seen_types and len(result["chunks"]) < 8:
            result["chunks"].append(c)
            seen_types.add(dt)

    return {**state, "retrieved_evidence": result["chunks"]}


def run_specialist_agents_node(state: dict) -> dict:
    """Node 4 – Order + Policy agents."""
    state = run_order_agent(state)
    state = run_policy_agent(state)
    return state


def verify_claims_node(state: dict) -> dict:
    """Node 5 – verify every claim against evidence."""
    return run_verifier(state)


def decide_action_node(state: dict) -> dict:
    """Node 6 – generate action drafts."""
    return run_action_agent(state)


def final_response_node(state: dict) -> dict:
    """Node 7 – format final output."""
    answer = state.get("final_answer") or {}
    return {
        **state,
        "final_answer": {
            **answer,
            "status": "complete",
            "message": "BuyWise Agent analysis complete.",
        },
    }


# ── Conditional routing (all loop-guarded) ────────────────────────────────

def route_after_intent(
    state: dict,
) -> Literal["ingest_and_index", "final_response"]:
    return "ingest_and_index"


def route_after_ingest(
    state: dict,
) -> Literal["retrieve_evidence", "final_response"]:
    if state.get("_indexed_chunks", 0) > 0:
        return "retrieve_evidence"
    # No data parsed but still try
    return "retrieve_evidence"


def route_after_verify(
    state: dict,
) -> Literal["decide_action", "retrieve_evidence"]:
    """If unsupported claims exist, do one re-retrieval attempt."""
    attempts = state.get("retrieval_attempts", 0)
    if len(state.get("unsupported_claims", [])) > 0 and attempts < 2:
        return "retrieve_evidence"
    return "decide_action"


def route_after_action(state: dict) -> Literal["final_response"]:
    return "final_response"


# ── Build Graph ─────────────────────────────────────────────────────────────

def build_graph():
    """Build and compile the MVP LangGraph."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        raise ImportError("pip install langgraph>=0.4.0")

    workflow = StateGraph(BuyWiseState)

    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("ingest_and_index", ingest_and_index_node)
    workflow.add_node("retrieve_evidence", retrieve_evidence_node)
    workflow.add_node("run_specialist_agents", run_specialist_agents_node)
    workflow.add_node("verify_claims", verify_claims_node)
    workflow.add_node("decide_action", decide_action_node)
    workflow.add_node("final_response", final_response_node)

    workflow.set_entry_point("classify_intent")
    workflow.add_edge("classify_intent", "ingest_and_index")
    workflow.add_edge("ingest_and_index", "retrieve_evidence")
    workflow.add_edge("retrieve_evidence", "run_specialist_agents")
    workflow.add_edge("run_specialist_agents", "verify_claims")
    workflow.add_conditional_edges(
        "verify_claims",
        route_after_verify,
        {"decide_action": "decide_action", "retrieve_evidence": "retrieve_evidence"},
    )
    workflow.add_edge("decide_action", "final_response")
    workflow.add_edge("final_response", END)

    return workflow.compile()


# ── Runner ──────────────────────────────────────────────────────────────────

def run_workflow(
    user_query: str,
    uploaded_source_ids: list[str] | None = None,
    user_id: str = "default",
) -> dict[str, Any]:
    """Run the MVP warranty/return workflow."""
    global _RETRIEVER
    _RETRIEVER = None  # Reset so sample data is reloaded

    graph = build_graph()

    initial_state = {
        "user_id": user_id,
        "conversation_id": f"mvp_{abs(hash(user_query)) % 10**6:06x}",
        "task_id": f"task_{abs(hash(user_query)) % 10**6:06x}",
        "user_query": user_query,
        "uploaded_source_ids": uploaded_source_ids or [],
        "intent": None,
        "plan": {},
        "retrieved_evidence": [],
        "agent_messages": [],
        "verified_claims": [],
        "unsupported_claims": [],
        "pending_actions": [],
        "retrieval_attempts": 0,
        "final_answer": None,
        "errors": [],
        "cache_keys": {},
        "product_facts": None,
    }

    config = {"configurable": {"thread_id": initial_state["conversation_id"]}}
    return graph.invoke(initial_state, config)
