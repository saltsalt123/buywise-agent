"""Golden tests: the structured shape of each case's output.

Only machine-readable fields are pinned — status, intent, confidence, action ids, claim ids,
the policy figures and the evidence set.  The natural-language summary is deliberately *not*
compared: wording changes are not regressions, while a lost action or a flipped status is.

The expected values below are the measured output of the four cases, not aspirations; the
contradictory case is the one whose expectation the conflict-handling fix has to reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.graph import run_workflow
from tests.case_fixtures import contradictory_case

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data"

HEADPHONE_QUERY = "My headphones stopped charging after 7 months. Can I claim warranty?"
LAPTOP_QUERY = "Can I return this laptop I bought on May 15?"
RETURN_QUERY = "Can I return this laptop I bought last week?"


def _policy_fields(result: dict) -> dict:
    """The policy figures the workflow actually published, read back from claim texts."""
    fields: dict[str, str] = {}
    for claim in result.get("verified_claims", []) + result.get("unsupported_claims", []):
        if claim.claim_id == "policy_return_window":
            fields["return_window_claim"] = claim.text
        elif claim.claim_id == "policy_warranty_period":
            fields["warranty_period_claim"] = claim.text
        elif claim.claim_id == "policy_return_valid":
            fields["return_verdict"] = "valid"
        elif claim.claim_id == "policy_return_expired":
            fields["return_verdict"] = "expired"
        elif claim.claim_id == "policy_return_conflict":
            fields["return_conflict"] = claim.text
        elif claim.claim_id == "policy_warranty_valid":
            fields["warranty_verdict"] = "valid"
        elif claim.claim_id == "policy_warranty_expired":
            fields["warranty_verdict"] = "expired"
    return fields


def _snapshot(result: dict) -> dict:
    answer = result.get("final_answer") or {}
    chunks = result.get("retrieved_evidence") or []
    return {
        "status": answer.get("status"),
        "intent": result.get("intent"),
        "overall_confidence": answer.get("overall_confidence"),
        "action_ids": sorted(a.get("action_id") for a in answer.get("actions", [])),
        "verified_ids": sorted(c.claim_id for c in result.get("verified_claims", [])),
        "unsupported_ids": sorted(c.claim_id for c in result.get("unsupported_claims", [])),
        "policy": _policy_fields(result),
        "evidence_count": len(chunks),
        "doc_types": sorted({c.metadata.get("doc_type") for c in chunks}),
        "chunk_ids_unique": len({c.chunk_id for c in chunks}) == len(chunks),
        "retrieval_attempts": result.get("retrieval_attempts"),
        "summary": answer.get("summary", ""),
    }


# ── committed cases: measured behaviour ─────────────────────────────────────

HEADPHONE_EXPECTED = {
    "status": "complete",
    "intent": "warranty_or_return",
    "overall_confidence": 1.0,
    "action_ids": ["act_checklist", "act_return_exception_request", "act_warranty_claim"],
    "verified_ids": [
        "intent_classified",
        "order_amount",
        "order_purchase_date",
        "policy_exceptions",
        "policy_return_expired",
        "policy_return_window",
        "policy_warranty_period",
        "policy_warranty_valid",
    ],
    "unsupported_ids": [],
    "evidence_count": 15,
    "doc_types": ["email", "receipt", "warranty"],
    "retrieval_attempts": 1,
}

LAPTOP_EXPECTED = {
    "status": "complete",
    "intent": "warranty_or_return",
    "overall_confidence": 1.0,
    "action_ids": ["act_checklist", "act_return_exception_request"],
    "verified_ids": [
        "intent_classified",
        "order_amount",
        "order_purchase_date",
        "policy_return_expired",
        "policy_return_window",
    ],
    "unsupported_ids": [],
    "evidence_count": 12,
    "doc_types": ["bank_csv", "policy", "receipt"],
    "retrieval_attempts": 1,
}


@pytest.fixture(scope="module")
def headphone() -> dict:
    return _snapshot(run_workflow(HEADPHONE_QUERY, [str(SAMPLE / "headphone_warranty_case")]))


@pytest.fixture(scope="module")
def laptop() -> dict:
    return _snapshot(run_workflow(LAPTOP_QUERY, [str(SAMPLE / "laptop_return_case")]))


class TestHeadphoneGolden:
    @pytest.mark.parametrize("field", sorted(HEADPHONE_EXPECTED))
    def test_field(self, headphone: dict, field: str) -> None:
        assert headphone[field] == HEADPHONE_EXPECTED[field], (
            f"headphone golden mismatch on {field!r}"
        )

    def test_policy_fields(self, headphone: dict) -> None:
        assert headphone["policy"]["return_window_claim"].startswith("Return window: 30 days")
        assert headphone["policy"]["return_verdict"] == "expired"
        assert headphone["policy"]["warranty_period_claim"].startswith("Warranty period:")
        assert headphone["policy"]["warranty_verdict"] == "valid"
        assert "return_conflict" not in headphone["policy"]

    def test_evidence_is_well_formed(self, headphone: dict) -> None:
        assert headphone["chunk_ids_unique"], "chunk ids must be unique within a run"


class TestLaptopGolden:
    @pytest.mark.parametrize("field", sorted(LAPTOP_EXPECTED))
    def test_field(self, laptop: dict, field: str) -> None:
        assert laptop[field] == LAPTOP_EXPECTED[field], (
            f"laptop golden mismatch on {field!r}"
        )

    def test_policy_fields(self, laptop: dict) -> None:
        assert laptop["policy"]["return_window_claim"].startswith("Return window: 14 days")
        assert laptop["policy"]["return_verdict"] == "expired"
        assert "return_conflict" not in laptop["policy"]

    def test_evidence_is_well_formed(self, laptop: dict) -> None:
        assert laptop["chunk_ids_unique"]


class TestNoEvidenceGolden:
    @pytest.fixture(scope="class")
    def snapshot(self, tmp_path_factory: pytest.TempPathFactory) -> dict:
        empty = tmp_path_factory.mktemp("golden_empty")
        return _snapshot(run_workflow(RETURN_QUERY, [str(empty)]))

    def test_status(self, snapshot: dict) -> None:
        assert snapshot["status"] in {"no_evidence", "insufficient_evidence"}

    def test_intent_is_still_classified(self, snapshot: dict) -> None:
        assert snapshot["intent"] == "warranty_or_return"

    def test_confidence_is_zero(self, snapshot: dict) -> None:
        assert snapshot["overall_confidence"] == 0.0

    def test_no_documents_are_drafted(self, snapshot: dict) -> None:
        """The checklist is a prompt to go and find the documents, not a drafted document."""
        assert "act_return_request" not in snapshot["action_ids"]
        assert "act_warranty_claim" not in snapshot["action_ids"]
        assert snapshot["action_ids"] == ["act_checklist"]

    def test_nothing_is_verified(self, snapshot: dict) -> None:
        assert snapshot["verified_ids"] == []

    def test_only_the_intent_claim_is_unsupported(self, snapshot: dict) -> None:
        """The supervisor's routing line cannot be supported by documents that do not exist.

        Exactly one entry: the verifier must not re-collect its own previous message onto
        the second pass, which used to duplicate every claim in this list.
        """
        assert snapshot["unsupported_ids"] == ["intent_classified"]

    def test_no_policy_fields(self, snapshot: dict) -> None:
        assert snapshot["policy"] == {}

    def test_no_evidence(self, snapshot: dict) -> None:
        assert snapshot["evidence_count"] == 0

    def test_summary_names_the_missing_evidence(self, snapshot: dict) -> None:
        summary = snapshot["summary"].lower()
        assert sum(w in summary for w in ("receipt", "policy", "warranty")) >= 2


class TestContradictoryPolicyGolden:
    """Receipt grants a 30-day window; policy and support email refuse returns entirely."""

    @pytest.fixture(scope="class")
    def snapshot(self, tmp_path_factory: pytest.TempPathFactory) -> dict:
        src = contradictory_case(tmp_path_factory.mktemp("golden_conflict") / "case")
        return _snapshot(run_workflow(RETURN_QUERY, [src]))

    def test_reports_a_review_status(self, snapshot: dict) -> None:
        assert snapshot["status"] == "needs_human_review", (
            "a self-contradicting document set must not be reported as a completed analysis"
        )

    def test_no_plain_return_request_is_drafted(self, snapshot: dict) -> None:
        assert "act_return_request" not in snapshot["action_ids"], (
            "drafting a plain return request misrepresents a final-sale policy"
        )

    def test_an_exception_request_is_offered_instead(self, snapshot: dict) -> None:
        assert "act_return_exception_request" in snapshot["action_ids"]

    def test_confidence_is_not_certain(self, snapshot: dict) -> None:
        assert snapshot["overall_confidence"] != 1.0, (
            "contradictory evidence cannot support maximum confidence"
        )

    def test_conflict_is_recorded_as_a_policy_field(self, snapshot: dict) -> None:
        assert "return_conflict" in snapshot["policy"], snapshot["policy"]

    def test_summary_explains_the_conflict(self, snapshot: dict) -> None:
        summary = snapshot["summary"].lower()
        assert any(
            w in summary
            for w in ("conflict", "contradict", "inconsistent", "final sale", "no returns")
        ), f"summary does not explain the conflict: {snapshot['summary']!r}"

    def test_both_sides_of_the_conflict_reach_the_verifier(self, snapshot: dict) -> None:
        assert "policy_return_window" in snapshot["verified_ids"], (
            "the receipt's return window should still be recorded"
        )

    def test_evidence_is_well_formed(self, snapshot: dict) -> None:
        assert snapshot["chunk_ids_unique"]
        assert snapshot["evidence_count"] > 0
