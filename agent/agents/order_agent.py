"""
Order Agent - extracts purchase details from receipts/order emails/bank CSVs.
"""
from __future__ import annotations

import re
from datetime import datetime

from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk, OrderFacts


def extract_date(text: str) -> str | None:
    """Try to extract a date from text."""
    # Match common date formats
    patterns = [
        r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def extract_amount(text: str) -> float | None:
    """Try to extract a monetary amount."""
    m = re.search(r"\$?(\d+\.\d{2})", text)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+\.\d{2})\s*USD", text)
    if m:
        return float(m.group(1))
    return None


def extract_order_number(text: str) -> str | None:
    """Try to extract an order number."""
    patterns = [
        r"order[#\s:]*([A-Z0-9\-]{6,20})",
        r"order\s*(?:number|id|no)[:#\s]*([A-Z0-9\-]{6,20})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def extract_product_model(text: str) -> str | None:
    """Try to extract a product model number."""
    patterns = [
        r"model[#\s:]*([A-Z0-9\-]{4,20})",
        r"sku[#\s:]*([A-Z0-9\-]{4,20})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def run_order_agent(state: dict) -> dict:
    """Extract order facts from evidence chunks."""
    chunks: list[EvidenceChunk] = state.get("retrieved_evidence", [])
    order_chunks = [c for c in chunks if c.metadata.get("doc_type") in ("receipt", "email", "bank_csv")]

    all_text = " ".join(c.text for c in order_chunks)

    facts = OrderFacts(
        purchase_date=extract_date(all_text),
        amount=extract_amount(all_text),
        order_number=extract_order_number(all_text),
        product_model=extract_product_model(all_text),
    )

    # Extract merchant name (heuristic)
    for chunk in order_chunks:
        if "amazon" in chunk.text.lower():
            facts.merchant = "Amazon"
            break
        if "walmart" in chunk.text.lower():
            facts.merchant = "Walmart"
            break
        if "best buy" in chunk.text.lower():
            facts.merchant = "Best Buy"
            break
        if "target" in chunk.text.lower():
            facts.merchant = "Target"
            break

    claims = []
    if facts.purchase_date:
        claims.append(
            Claim(
                claim_id="order_purchase_date",
                text=f"Purchase date: {facts.purchase_date}",
                claim_type=ClaimType.ORDER_FACT,
                confidence=0.85 if facts.merchant else 0.6,
            )
        )
    if facts.amount:
        claims.append(
            Claim(
                claim_id="order_amount",
                text=f"Amount paid: ${facts.amount:.2f}" if facts.amount else "Amount: unknown",
                claim_type=ClaimType.ORDER_FACT,
                confidence=0.85,
            )
        )
    if facts.merchant:
        claims.append(
            Claim(
                claim_id="order_merchant",
                text=f"Merchant: {facts.merchant}",
                claim_type=ClaimType.ORDER_FACT,
                confidence=0.8,
            )
        )

    message = AgentMessage(
        agent_name="order_agent",
        status="success" if claims else "needs_more_evidence",
        claims=claims,
        evidence_ids=[c.chunk_id for c in order_chunks],
        confidence=0.85 if claims else 0.3,
        next_actions=["policy_agent"],
    )

    return {
        **state,
        "agent_messages": state.get("agent_messages", []) + [message],
    }
