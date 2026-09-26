"""
BuyWise Agent MVP — Minimal FastAPI backend.

``source_dirs`` arrives from the caller and used to be handed straight to ``run_workflow``,
which resolves each entry and reads every file inside it.  Any caller could therefore point
the service at ``/tmp/loopcase``, ``/etc`` or a home directory and have the contents parsed
into the answer — a local file-disclosure primitive rather than a feature.

Reads are now restricted to ``SAFE_SOURCE_ROOTS``.  The check resolves symlinks and ``..``
before comparing, so neither can be used to escape, and it runs *before* the workflow is
entered so a rejected request costs no ingestion work and returns nothing.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.graph import run_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Directories the API is allowed to read documents from. Everything else is refused.
SAFE_SOURCE_ROOTS: tuple[Path, ...] = (PROJECT_ROOT / "sample_data",)

app = FastAPI(title="BuyWise Agent MVP", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    query: str
    source_dirs: list[str] = ["sample_data/headphone_warranty_case"]


class ChatResponse(BaseModel):
    status: str
    intent: str | None = None
    summary: str = ""
    key_facts: list[dict] = []
    actions: list[dict] = []
    evidence_count: int = 0
    confidence: float = 0.0
    raw: dict | None = None


def resolve_source_dirs(source_dirs: list[str]) -> list[str]:
    """Resolve each requested path and refuse anything outside ``SAFE_SOURCE_ROOTS``.

    Relative paths are taken from the project root.  ``Path.resolve()`` follows symlinks and
    collapses ``..`` before the comparison, so both escape routes are closed.
    """
    roots = [root.resolve() for root in SAFE_SOURCE_ROOTS]
    resolved: list[str] = []

    for raw in source_dirs:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        resolved_path = candidate.resolve()

        permitted = any(
            resolved_path == root or resolved_path.is_relative_to(root) for root in roots
        )
        if not permitted:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"source_dirs entry {raw!r} is outside the allowed roots "
                    f"({', '.join(str(r) for r in roots)})"
                ),
            )
        resolved.append(str(resolved_path))

    return resolved


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Run the MVP warranty/return workflow."""
    # Validated before the try block: an HTTPException raised inside it would be swallowed
    # by the `except Exception` below and reported as a 500.
    allowed_dirs = resolve_source_dirs(req.source_dirs)

    try:
        result = run_workflow(req.query, allowed_dirs)
        answer = result.get("final_answer") or {}
        return ChatResponse(
            status=answer.get("status") or "complete",
            intent=result.get("intent"),
            summary=answer.get("summary", ""),
            key_facts=answer.get("key_facts", []),
            actions=answer.get("actions", []),
            evidence_count=len(result.get("retrieved_evidence", [])),
            confidence=answer.get("overall_confidence", 0),
            raw=answer,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "buywise-agent-mvp"}
