"""Verifier strictness: a claim is only verified when the evidence actually supports it.

The verifier used to promote any claim at ``confidence >= 0.7`` even with no supporting
chunk at all::

    elif claim.confidence >= 0.7:
        # High confidence claim with no explicit support - still pass but note
        verified.append(claim)

That made the verifier a rubber stamp for exactly the claims most in need of checking —
the confident ones.  Support was also decided by substring overlap over raw query tokens,
so a claim could be "supported" by shared filler words such as ``return`` or ``days``
without the evidence stating the same fact.

The cases below are the assertions that have to hold instead.
"""

from __future__ import annotations

from agent.agents.verifier_agent import run_verifier
from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk


def _verify(evidence_texts: list[str], claim_text: str, confidence: float) -> tuple[list, list]:
    """Run the real verifier over one claim and return (verified, unsupported)."""
    state = {
        "agent_messages": [
            AgentMessage(
                agent_name="test_agent",
                claims=[
                    Claim(
                        claim_id="c1",
                        text=claim_text,
                        claim_type=ClaimType.POLICY_RULE,
                        confidence=confidence,
                    )
                ],
            )
        ],
        "retrieved_evidence": [
            EvidenceChunk(chunk_id=f"e{i}", source_id="s1", text=t)
            for i, t in enumerate(evidence_texts)
        ],
    }
    out = run_verifier(state)
    return out["verified_claims"], out["unsupported_claims"]


class TestConfidenceIsNotEvidence:
    """A high confidence score with nothing behind it must not reach ``verified``."""

    def test_case_a_unrelated_evidence(self) -> None:
        verified, unsupported = _verify(
            ["Zzz qqq wobble"], "The product has a 30-day return window", 0.9
        )
        assert verified == [], "a claim with no supporting chunk was verified"
        assert len(unsupported) == 1

    def test_case_c_different_policy_fact(self) -> None:
        """Evidence about a warranty says nothing about a return window."""
        verified, unsupported = _verify(
            ["Warranty period: 1 year"], "Return window is 30 days", 0.9
        )
        assert verified == [], "a warranty period was accepted as support for a return window"
        assert len(unsupported) == 1

    def test_no_evidence_at_all(self) -> None:
        verified, unsupported = _verify([], "The product has a 30-day return window", 0.99)
        assert verified == [], "a claim was verified with an empty evidence set"
        assert len(unsupported) == 1


class TestContradictedClaimsAreNotVerified:
    def test_case_b_evidence_forbids_returns(self) -> None:
        verified, unsupported = _verify(
            ["Returns are not accepted after delivery"],
            "The product can be returned within 30 days",
            0.9,
        )
        assert verified == [], "evidence stating returns are refused still verified a return"
        assert len(unsupported) == 1


class TestWeakKeywordOverlapIsNotSupport:
    """Shared filler words must not be mistaken for agreement."""

    def test_shared_words_without_the_stated_number(self) -> None:
        """``return`` and ``days`` both appear, but nothing states a 30-day window."""
        verified, unsupported = _verify(
            ["You may return the item. Business days only."],
            "The return window is 30 days.",
            0.9,
        )
        assert verified == [], (
            "shared words 'return'/'days' were treated as support for a 30-day window "
            "that the evidence never states"
        )
        assert len(unsupported) == 1

    def test_different_window_lengths_do_not_support_each_other(self) -> None:
        verified, unsupported = _verify(
            ["Return window is 14 days from delivery"],
            "The return window is 30 days",
            0.9,
        )
        assert verified == [], "a 14-day window was accepted as support for a 30-day claim"
        assert len(unsupported) == 1


class TestRealSupportStillVerifies:
    """Control cases: the strictness must not reject genuinely supported claims."""

    def test_matching_window_is_verified(self) -> None:
        verified, unsupported = _verify(
            ["Return Window: 14 days from delivery"], "The return window is 14 days", 0.9
        )
        assert len(verified) == 1, "a claim matching the evidence was wrongly rejected"
        assert unsupported == []
        assert verified[0].supported_by, "a verified claim must cite the chunk that supports it"

    def test_evidence_repeating_the_fact_is_verified(self) -> None:
        verified, _ = _verify(
            ["Store #12 2026-05-15 Total 1299.00", "Date: 2026-05-15 16:20:00"],
            "Purchase date: 2026-05-15",
            0.85,
        )
        assert len(verified) == 1, "the purchase date is quoted verbatim in the evidence"


class TestUnsupportedClaimsCarryAReason:
    def test_reason_is_recorded(self) -> None:
        _, unsupported = _verify(["Zzz qqq wobble"], "The product can be returned", 0.9)
        assert len(unsupported) == 1
        claim = unsupported[0]
        assert claim.uncertainty, "an unsupported claim must record why it is unsupported"

    def test_verified_claims_are_not_marked_uncertain(self) -> None:
        verified, _ = _verify(
            ["Return Window: 14 days from delivery"], "The return window is 14 days", 0.9
        )
        assert len(verified) == 1
        assert not verified[0].uncertainty, "a supported claim should not carry an uncertainty"
