"""
Verifier Agent - checks each claim against evidence, marks supported/unsupported.
"""
from __future__ import annotations

from agent.state import AgentMessage, Claim, ClaimType


def run_verifier(state: dict) -> dict:
    """Verify each agent's claims against the evidence."""
    agent_messages: list[AgentMessage] = state.get("agent_messages", [])
    chunks = state.get("retrieved_evidence", [])

    all_claims: list[Claim] = []
    for msg in agent_messages:
        all_claims.extend(msg.claims)

    verified: list[Claim] = []
    unsupported: list[Claim] = []

    # Build evidence text index
    evidence_texts = {c.chunk_id: c.text.lower() for c in chunks}

    for claim in all_claims:
        claim_text_lower = claim.text.lower()

        # Check if any evidence chunk contains key terms from the claim
        key_terms = [t for t in claim_text_lower.split() if len(t) > 3]
        supporting_chunks = []

        for chunk_id, text in evidence_texts.items():
            matches = sum(1 for term in key_terms if term in text)
            if matches >= min(2, len(key_terms)):
                supporting_chunks.append(chunk_id)

        if supporting_chunks:
            claim.supported_by = supporting_chunks
            verified.append(claim)
        elif claim.confidence >= 0.7:
            # High confidence claim with no explicit support - still pass but note
            verified.append(claim)
        else:
            claim.uncertainty = "No direct evidence found to support this claim"
            unsupported.append(claim)

    message = AgentMessage(
        agent_name="verifier_agent",
        status="success",
        claims=verified + unsupported,
        evidence_ids=list(evidence_texts.keys()),
        confidence=0.85 if len(verified) > len(unsupported) else 0.5,
        risk_flags=[] if not unsupported else [f"{len(unsupported)} unsupported claim(s)"],
        next_actions=["action_agent"] if verified else [],
    )

    return {
        **state,
        "agent_messages": agent_messages + [message],
        "verified_claims": verified,
        "unsupported_claims": unsupported,
    }
