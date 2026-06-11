"""
Product Agent - extracts product specs and checks warranty coverage for the issue.
"""
from __future__ import annotations

import re

from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk, ProductFacts


def run_product_agent(state: dict) -> dict:
    """Extract product facts and check if the user's issue is covered."""
    chunks: list[EvidenceChunk] = state.get("retrieved_evidence", [])
    manual_chunks = [c for c in chunks if c.metadata.get("doc_type") in ("manual", "product_page")]
    query = state.get("user_query", "").lower()

    all_text = " ".join(c.text for c in manual_chunks)

    facts = ProductFacts()

    # Extract model
    model_m = re.search(r"model[#\s:]*([A-Z0-9\-]{4,20})", all_text, re.IGNORECASE)
    if model_m:
        facts.model = model_m.group(1)

    # Extract brand
    brand_m = re.search(r"(?:brand|by|manufacturer)[:\s]+([A-Z][a-zA-Z\s]{2,20})", all_text)
    if brand_m:
        facts.brand = brand_m.group(1).strip()

    # Extract specs (basic pairs like "Power: 1500W")
    spec_pairs = re.findall(r"([A-Za-z\s]+)[:\s]+([\d.]+[A-Za-z%°]*)\s*", all_text)
    for key, val in spec_pairs[:10]:
        facts.specs[key.strip()] = val.strip()

    # Check if the user's issue is mentioned in the manual
    issue_keywords = ["charging", "battery", "power", "overheat", "noise", "leak", "crack", "display", "button", "connect", "bluetooth", "wifi"]
    for kw in issue_keywords:
        if kw in query and kw in all_text:
            facts.known_issues.append(f"Manual mentions '{kw}' (relevant to user's issue)")

    claims = []
    if facts.model or facts.brand:
        name = f"{facts.brand or ''} {facts.model or ''}".strip()
        claims.append(
            Claim(
                claim_id="product_identity",
                text=f"Product: {name or 'Unknown'}",
                claim_type=ClaimType.ORDER_FACT,
                confidence=0.75,
            )
        )
    if facts.known_issues:
        claims.append(
            Claim(
                claim_id="product_issue_coverage",
                text="Issue type is discussed in product documentation: " + "; ".join(facts.known_issues),
                claim_type=ClaimType.POLICY_RULE,
                confidence=0.7,
            )
        )

    message = AgentMessage(
        agent_name="product_agent",
        status="success",
        claims=claims,
        evidence_ids=[c.chunk_id for c in manual_chunks],
        confidence=0.7 if claims else 0.4,
        next_actions=["verifier_agent"],
    )

    return {
        **state,
        "agent_messages": state.get("agent_messages", []) + [message],
        "product_facts": facts,
    }
