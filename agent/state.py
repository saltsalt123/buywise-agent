"""
BuyWise Agent - Core data models and types.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


# ── Document / Evidence Models ──────────────────────────────────────────────

class DocType(str, Enum):
    RECEIPT = "receipt"
    WARRANTY = "warranty"
    MANUAL = "manual"
    POLICY = "policy"
    EMAIL = "email"
    BANK_CSV = "bank_csv"
    REVIEWS = "reviews"
    PRODUCT_PAGE = "product_page"


class SourceDocument(BaseModel):
    source_id: str
    user_id: str
    file_hash: str
    doc_type: DocType
    title: str
    created_at: datetime
    metadata: dict[str, Any] = {}


class EvidenceChunk(BaseModel):
    chunk_id: str
    source_id: str
    text: str
    page: int | None = None
    row_id: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = {}
    trust_score: float = 1.0
    embedding: list[float] | None = None


class ParsedObjectType(str, Enum):
    ORDER = "order"
    TRANSACTION = "transaction"
    WARRANTY_TERM = "warranty_term"
    PRODUCT_SPEC = "product_spec"
    REVIEW_ISSUE = "review_issue"
    POLICY_RULE = "policy_rule"


class ParsedObject(BaseModel):
    object_id: str
    source_id: str
    object_type: ParsedObjectType
    fields: dict[str, Any]
    evidence_chunk_ids: list[str] = []


# ── Agent Communication Models ──────────────────────────────────────────────

class ClaimType(str, Enum):
    ORDER_FACT = "order_fact"
    POLICY_RULE = "policy_rule"
    RISK = "risk"
    RECOMMENDATION = "recommendation"
    ACTION = "action"


class Claim(BaseModel):
    claim_id: str
    text: str
    claim_type: ClaimType
    supported_by: list[str] = []
    confidence: float
    uncertainty: str | None = None


class AgentMessage(BaseModel):
    agent_name: str
    status: Literal["success", "needs_more_evidence", "failed"] = "success"
    claims: list[Claim] = []
    evidence_ids: list[str] = []
    confidence: float = 0.0
    risk_flags: list[str] = []
    next_actions: list[str] = []
    handoff_to: str | None = None


class PendingAction(BaseModel):
    action_id: str
    action_type: Literal["draft_email", "create_watch", "export_report"]
    description: str
    payload: dict[str, Any]
    requires_approval: bool = True
    approved: bool = False


# ── Intent / Task Models ────────────────────────────────────────────────────

class IntentType(str, Enum):
    WARRANTY_RETURN = "warranty_or_return"
    PURCHASE_DECISION = "purchase_decision"
    PRICE_MONITOR = "price_monitoring"
    GENERAL_QA = "general_qa"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Parsed Result Models ────────────────────────────────────────────────────

class OrderFacts(BaseModel):
    purchase_date: str | None = None
    merchant: str | None = None
    amount: float | None = None
    order_number: str | None = None
    product_model: str | None = None
    product_name: str | None = None


class PolicyDecision(BaseModel):
    return_window_days: int | None = None
    warranty_period: str | None = None
    warranty_terms: list[str] = []
    exceptions: list[str] = []
    is_return_valid: bool | None = None
    is_warranty_valid: bool | None = None
    confidence: float = 0.0


class ProductFacts(BaseModel):
    model: str | None = None
    brand: str | None = None
    specs: dict[str, Any] = {}
    known_issues: list[str] = []


class ReviewSummary(BaseModel):
    overall_rating: float | None = None
    top_positive_themes: list[str] = []
    top_negative_themes: list[str] = []
    common_issues: list[str] = []
    fake_review_flags: list[str] = []


class PriceInsight(BaseModel):
    current_price: float | None = None
    lowest_price_30d: float | None = None
    highest_price_30d: float | None = None
    price_trend: Literal["rising", "falling", "stable"] | None = None
    drop_from_peak_pct: float | None = None


class RiskFlags(BaseModel):
    flags: list[str] = []
    low_credibility_sources: list[str] = []
    policy_conflicts: list[str] = []


# ── LangGraph State ─────────────────────────────────────────────────────────

class BuyWiseState(TypedDict):
    """Full workflow state for LangGraph execution."""

    # Identity
    user_id: str
    conversation_id: str
    task_id: str

    # Input
    user_query: str
    intent: str | None
    uploaded_source_ids: list[str]

    # Workflow
    plan: dict[str, Any]
    retrieved_evidence: list[EvidenceChunk]
    agent_messages: list[AgentMessage]
    verified_claims: list[Claim]
    unsupported_claims: list[Claim]
    pending_actions: list[PendingAction]
    retrieval_attempts: int  # ← loop guard counter

    # Output
    final_answer: dict[str, Any] | None
    errors: list[str]
    cache_keys: dict[str, str]

    # Optional extra fields for agents
    product_facts: Any | None


# ── Async Task ──────────────────────────────────────────────────────────────

class AsyncTask(BaseModel):
    task_id: str
    user_id: str = "default"
    task_type: str
    status: TaskStatus = TaskStatus.QUEUED
    input_data: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None


# ── Eval ────────────────────────────────────────────────────────────────────

class EvalCase(BaseModel):
    case_id: str
    user_query: str
    input_sources: list[str]
    expected_decision: str | None = None
    gold_evidence_ids: list[str] = []
    forbidden_claims: list[str] = []
    expected_actions: list[str] = []


# ── Helpers ─────────────────────────────────────────────────────────────────

def make_chunk_id(source_id: str, page: int | None, row_id: str | None, index: int) -> str:
    raw = f"{source_id}:p{page}:r{row_id}:i{index}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def make_claim_id(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def hash_content(content: str | bytes) -> str:
    if isinstance(content, bytes):
        return hashlib.sha256(content).hexdigest()
    return hashlib.sha256(content.encode()).hexdigest()
