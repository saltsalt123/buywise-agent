"""
Verifier Agent - checks each claim against evidence, marks supported/unsupported.

A claim is verified only when a retrieved chunk actually supports it.  Two things used to
break that promise:

1. ``elif claim.confidence >= 0.7: verified.append(claim)`` promoted any confident claim
   with no supporting chunk at all.  The verifier was therefore least effective on exactly
   the claims that most needed checking.
2. Support was a substring count over raw query tokens, so overlapping filler such as
   ``return`` or ``days`` was enough to "support" a figure the evidence never stated.

Support is now decided on token boundaries, and the load-bearing rule is the quantity
check: a claim that asserts a number must find that number in the evidence.  A 14-day
policy cannot support a 30-day claim, and filler that merely shares ``return``/``days``
fails the same test.  Claims that assert no quantity (a merchant name, or a verdict the
policy agent derived such as "the return window has closed") still require at least one
content term to appear in the chunk.

Known limit, stated rather than hidden: this is lexical verification.  It cannot detect a
semantic contradiction between two claims that use the same words, and a derived verdict is
accepted on the strength of the terms it shares with the document it came from.
"""
from __future__ import annotations

from agent.state import AgentMessage, Claim
from agent.textnorm import content_terms, numeric_terms, tokenize


def _chunk_supports(claim: Claim, chunk_text: str) -> bool:
    """True when this chunk states the claim's facts, not merely some of its words."""
    tokens = set(tokenize(chunk_text))

    claim_numbers = numeric_terms(claim.text)
    if claim_numbers:
        # The quantity is the sharpest signal available. "30 days" is not supported by a
        # chunk that only ever says "14 days", and a claim whose only overlap with the
        # evidence is filler ("return", "days") asserts a figure the evidence lacks.
        return claim_numbers <= tokens

    claim_terms = content_terms(claim.text)
    if not claim_terms:
        return False
    # No quantity to check, so require the document to share at least one content term.
    # Deliberately not "all terms": a claim paraphrases its source, and the derived
    # verdicts ("The return window has closed") use wording the document never repeats.
    return bool(claim_terms & tokens)


def run_verifier(state: dict) -> dict:
    """Verify each agent's claims against the evidence."""
    agent_messages: list[AgentMessage] = state.get("agent_messages", [])
    chunks = state.get("retrieved_evidence", [])

    all_claims: list[Claim] = []
    for msg in agent_messages:
        # Never re-verify our own previous output. The verifier's message carries the claims
        # it already judged, and on the second pass (after a re-retrieval) those same claims
        # were being collected again — so every claim appeared twice in `unsupported_claims`
        # and the "uncertainties" list showed the same item more than once.
        if msg.agent_name == "verifier_agent":
            continue
        all_claims.extend(msg.claims)

    verified: list[Claim] = []
    unsupported: list[Claim] = []

    # Build evidence text index
    evidence_texts = {c.chunk_id: c.text.lower() for c in chunks}

    for claim in all_claims:
        supporting_chunks = [
            chunk_id
            for chunk_id, text in evidence_texts.items()
            if _chunk_supports(claim, text)
        ]

        if supporting_chunks:
            claim.supported_by = supporting_chunks
            claim.uncertainty = None
            verified.append(claim)
        else:
            claim.supported_by = []
            claim.uncertainty = (
                "No evidence found that states this; a confidence score is not evidence"
            )
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
