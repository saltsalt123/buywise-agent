"""
BuyWise Agent MVP — Minimal FastAPI backend.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.graph import run_workflow

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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Run the MVP warranty/return workflow."""
    try:
        result = run_workflow(req.query, req.source_dirs)
        answer = result.get("final_answer") or {}
        return ChatResponse(
            status="complete",
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
