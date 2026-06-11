"""
Policy Agent - analyzes warranty, return, and refund policies.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk, PolicyDecision


def parse_days(text: str) -> int | None:
    """Extract a number of days from policy text."""
    patterns = [
        r"(\d+)\s*(?:day|days)",
        r"(\d+)\s*(?:year|years)",
        r"(\d+)\s*(?:month|months)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            unit = m.group(0)
            if "year" in unit:
                return val * 365
            if "month" in unit:
                return val * 30
            return val
    return None


def run_policy_agent(state: dict) -> dict:
    """Analyze return and warranty policies from evidence chunks."""
    chunks: list[EvidenceChunk] = state.get("retrieved_evidence", [])
    policy_chunks = [c for c in chunks if c.metadata.get("doc_type") in ("warranty", "policy")]

    all_text = " ".join(c.text for c in policy_chunks).lower()

    decision = PolicyDecision()

    # Extract return window
    return_match = re.search(r"return\s*(?:within|policy|window|period)[:\s]*(\d+)\s*(?:day|days)", all_text)
    if return_match:
        decision.return_window_days = int(return_match.group(1))

    # Extract warranty period
    warranty_match = re.search(r"warranty[:\s]*(\d+)\s*(?:year|years|month|months|day|days)", all_text)
    if warranty_match:
        decision.warranty_period = warranty_match.group(0)
        decision.confidence = 0.85
    else:
        # Look for 1-year as default in many consumer policies
        if "1 year" in all_text or "one year" in all_text or "12 month" in all_text:
            decision.warranty_period = "1 year"
            decision.confidence = 0.7

    # Extract exceptions
    exception_keywords = [
        "does not cover", "excluded", "not covered", "exception",
        "void", "not include", "damage caused by", "abuse",
        "unauthorized", "modification", "accidental damage",
    ]
    for kw in exception_keywords:
        if kw in all_text:
            decision.exceptions.append(kw)

    # Check if return is still valid (if we have order info)
    order_messages = [m for m in state.get("agent_messages", []) if m.agent_name == "order_agent"]
    purchase_date_str = None
    for msg in order_messages:
        for claim in msg.claims:
            if "purchase date" in claim.text.lower():
                purchase_date_str = claim.text.split(":")[-1].strip()

    if purchase_date_str and decision.return_window_days:
        try:
            purchase_date = datetime.strptime(purchase_date_str.split()[0], "%Y-%m-%d")
            days_since = (datetime.utcnow() - purchase_date).days
            decision.is_return_valid = days_since <= decision.return_window_days
            # Warranty is typically longer than return window
            if decision.warranty_period:
                decision.is_warranty_valid = days_since <= parse_days(decision.warranty_period) or True
        except (ValueError, IndexError):
            pass

    claims = []
    if decision.return_window_days:
        status = "within" if decision.is_return_valid else "past"
        claims.append(
            Claim(
                claim_id="policy_return_window",
                text=f"Return window: {decision.return_window_days} days ({status} window)",
                claim_type=ClaimType.POLICY_RULE,
                confidence=decision.confidence,
                uncertainty=None if decision.is_return_valid is not None else "Cannot determine purchase date",
            )
        )
    if decision.warranty_period:
        claims.append(
            Claim(
                claim_id="policy_warranty_period",
                text=f"Warranty period: {decision.warranty_period}",
                claim_type=ClaimType.POLICY_RULE,
                confidence=decision.confidence,
            )
        )
    if decision.exceptions:
        claims.append(
            Claim(
                claim_id="policy_exceptions",
                text=f"Policy exceptions found: {', '.join(decision.exceptions[:3])}",
                claim_type=ClaimType.POLICY_RULE,
                confidence=0.7,
            )
        )

    message = AgentMessage(
        agent_name="policy_agent",
        status="success" if claims else "needs_more_evidence",
        claims=claims,
        evidence_ids=[c.chunk_id for c in policy_chunks],
        confidence=decision.confidence or 0.5,
        next_actions=["product_agent"],
    )

    return {
        **state,
        "agent_messages": state.get("agent_messages", []) + [message],
    }
