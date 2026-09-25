"""The policy agent reads structure before prose.

Field values now come from the label/value pairs captured at ingestion, with the text patterns
kept as a fallback for anything unlabelled. Both halves need pinning, and the structured path
needs proving: an agent that ignores its input and a fallback that silently produces the same
answer are indistinguishable from the outside.
"""

from __future__ import annotations

from agent.agents.policy_agent import run_policy_agent
from agent.state import EvidenceChunk


def _chunk(text: str, labels: dict | None, doc_type: str = "policy") -> EvidenceChunk:
    metadata: dict = {"doc_type": doc_type}
    if labels is not None:
        metadata["labels"] = labels
    return EvidenceChunk(chunk_id="c1", source_id="s1", text=text, metadata=metadata)


def _claims(chunks: list[EvidenceChunk]) -> list:
    result = run_policy_agent({"retrieved_evidence": chunks, "agent_messages": []})
    return result["agent_messages"][-1].claims


def _claim_text(claims: list, claim_id: str) -> str:
    """Text of a claim that must exist, so a missing one fails loudly rather than as None."""
    match = next((c for c in claims if c.claim_id == claim_id), None)
    assert match is not None, f"no {claim_id} in {[c.claim_id for c in claims]}"
    return match.text


def _has_claim(claims: list, claim_id: str) -> bool:
    return any(c.claim_id == claim_id for c in claims)


class TestLabelsAreUsed:
    def test_labelled_value_is_taken(self):
        claims = _claims([_chunk("x", {"return window": "45 days from delivery"})])
        assert _claim_text(claims, "policy_return_window") == (
            "Return window: 45 days (undetermined window)"
        )

    def test_labels_win_over_a_conflicting_pattern(self):
        """The whole point of structured extraction: the pairing beats a regex sweep."""
        claims = _claims(
            [_chunk("Return Policy: 30 days from purchase date", {"return window": "45 days"})]
        )
        assert "45 days" in _claim_text(claims, "policy_return_window")

    def test_labelled_warranty_is_read(self):
        claims = _claims([_chunk("x", {"warranty period": "2 years"})])
        assert _claim_text(claims, "policy_warranty_period") == "Warranty period: 2 years"

    def test_hyphenated_label_value_is_understood(self):
        claims = _claims([_chunk("x", {"return policy": "30-day return window"})])
        assert "30 days" in _claim_text(claims, "policy_return_window")


class TestTextFallbackStillWorks:
    def test_unlabelled_text_falls_back_to_the_pattern(self):
        claims = _claims([_chunk("Return Policy: 30 days from purchase date", None)])
        assert _claim_text(claims, "policy_return_window") == (
            "Return window: 30 days (undetermined window)"
        )

    def test_empty_labels_dict_falls_back(self):
        claims = _claims([_chunk("RETURN POLICY: 30-day return window", {})])
        assert "30 days" in _claim_text(claims, "policy_return_window")

    def test_unlabelled_hyphenated_text_still_parses(self):
        claims = _claims([_chunk("Return Policy: 14-day window", None)])
        assert "14 days" in _claim_text(claims, "policy_return_window")

    def test_unparseable_value_produces_no_window_claim(self):
        claims = _claims([_chunk("nothing relevant here", {})])
        assert not _has_claim(claims, "policy_return_window")


class TestLabelsCarryAcrossChunks:
    def test_chunk_labels_are_merged(self):
        claims = _claims(
            [
                _chunk("header", {}, doc_type="policy"),
                _chunk("body", {"return window": "10 days"}, doc_type="receipt"),
            ]
        )
        assert "10 days" in _claim_text(claims, "policy_return_window")

    def test_first_occurrence_wins(self):
        claims = _claims(
            [
                _chunk("a", {"return window": "7 days"}),
                _chunk("b", {"return window": "99 days"}),
            ]
        )
        assert "7 days" in _claim_text(claims, "policy_return_window")
