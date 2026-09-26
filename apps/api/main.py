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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.graph import run_workflow

# The roots live in apps/safe_paths.py so the API and the Streamlit UI cannot drift apart:
# a directory the UI writes but the API refuses would be a broken UI. Re-exported here
# because this module is where callers and tests have always read SAFE_SOURCE_ROOTS from.
from apps.safe_paths import (  # noqa: F401  (re-exported for callers and tests)
    SAFE_SOURCE_ROOTS,
    UnsafeUploadError,
    resolve_within_safe_roots,
)

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
    collapses ``..`` before the comparison, so both escape routes are closed.  The shared
    helper does the work; this wrapper only translates the refusal into HTTP.
    """
    resolved: list[str] = []
    for raw in source_dirs:
        try:
            resolved.append(str(resolve_within_safe_roots(raw)))
        except UnsafeUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
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
