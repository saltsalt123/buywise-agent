"""Behaviour when there is no evidence at all.

Measured before the fix, with an empty source directory and a query containing the word
"return"::

    status             = complete
    overall_confidence = 1.0
    actions            = ['act_return_request', 'act_checklist']
    evidence_count     = 0

Three separate faults produced that answer:

1. ``final_response_node`` stamped ``status="complete"`` unconditionally, so a run with
   no evidence was indistinguishable from a real analysis.
2. ``action_agent`` decided a return existed by looking for the substring ``return`` in
   any verified claim — and the supervisor's own claim text is
   ``"Intent classified as: warranty_or_return"``.  The user's question was being used as
   evidence for the user's question.
3. ``_calc_confidence`` is ``verified / (verified + unsupported)``, so one verified claim
   with nothing to contradict it reported ``1.0`` — maximum confidence from zero evidence.

The fix has to make an evidence-free run say so, and refuse to draft documents on the
strength of the question alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.agents.action_agent import run_action_agent
from agent.graph import run_workflow
from agent.state import AgentMessage, Claim, ClaimType

QUERY_WITH_RETURN_WORD = "Can I return this laptop I bought on May 15?"

FORBIDDEN_ACTIONS = {"act_return_request", "act_warranty_claim"}

VALID_STATUSES = {"insufficient_evidence", "no_evidence"}


def _actions_for(verified: list[Claim]) -> list[str]:
    result = run_action_agent(
        {"verified_claims": verified, "unsupported_claims": [], "intent": "warranty_or_return"}
    )
    return [action.action_id for action in result["pending_actions"]]


def _supervisor_claim() -> Claim:
    """The intent claim the supervisor always emits, verbatim."""
    return Claim(
        claim_id="intent_classified",
        text="Intent classified as: warranty_or_return",
        claim_type=ClaimType.ORDER_FACT,
        confidence=0.9,
    )


class TestActionAgentDoesNotMineTheQuestion:
    """The question must never be its own evidence."""

    def test_intent_claim_alone_does_not_produce_a_return_request(self) -> None:
        actions = _actions_for([_supervisor_claim()])
        assert "act_return_request" not in actions, (
            "the supervisor's intent text contains the word 'return', and that was being "
            "treated as evidence that a return is available"
        )

    def test_intent_claim_alone_does_not_produce_a_warranty_claim(self) -> None:
        actions = _actions_for([_supervisor_claim()])
        assert "act_warranty_claim" not in actions

    def test_supervisor_message_round_trip(self) -> None:
        """Same assertion through the real supervisor output shape."""
        result = run_action_agent(
            {
                "verified_claims": [_supervisor_claim()],
                "unsupported_claims": [],
                "intent": "warranty_or_return",
                "agent_messages": [
                    AgentMessage(agent_name="supervisor", claims=[_supervisor_claim()])
                ],
            }
        )
        ids = [a.action_id for a in result["pending_actions"]]
        assert not (FORBIDDEN_ACTIONS & set(ids)), f"drafted documents from the question: {ids}"


class TestEmptySourceDirectory:
    @pytest.fixture()
    def empty_dir(self, tmp_path: Path) -> str:
        target = tmp_path / "empty"
        target.mkdir()
        return str(target)

    def test_status_reports_missing_evidence(self, empty_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [empty_dir])
        answer = result.get("final_answer") or {}
        assert answer.get("status") in VALID_STATUSES, (
            f"status={answer.get('status')!r} — a run with no evidence must not report success"
        )

    def test_confidence_is_not_one(self, empty_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [empty_dir])
        answer = result.get("final_answer") or {}
        assert answer.get("overall_confidence") != 1.0, (
            "maximum confidence was reported from zero evidence"
        )
        assert answer.get("overall_confidence") == 0.0

    def test_no_documents_are_drafted(self, empty_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [empty_dir])
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}
        assert not (FORBIDDEN_ACTIONS & ids), f"drafted documents with no evidence: {sorted(ids)}"

    def test_answer_names_the_missing_evidence(self, empty_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [empty_dir])
        answer = result.get("final_answer") or {}
        summary = str(answer.get("summary", "")).lower()
        named = [w for w in ("receipt", "policy", "warranty") if w in summary]
        assert len(named) >= 2, (
            f"summary should say which evidence is missing; it named only {named}: {summary!r}"
        )
        explained = ("insufficient", "no evidence", "missing", "not found", "could not")
        assert any(w in summary for w in explained), (
            f"summary does not explain the lack of evidence: {summary!r}"
        )

    def test_no_evidence_was_retrieved(self, empty_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [empty_dir])
        assert not result.get("retrieved_evidence")


class TestDirectoryWithNothingParsable:
    @pytest.fixture()
    def unparsable_dir(self, tmp_path: Path) -> str:
        target = tmp_path / "unparsable"
        target.mkdir()
        (target / "scan.bin").write_bytes(b"\x00\x01\x02\x03not a supported document")
        (target / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return str(target)

    def test_status_reports_missing_evidence(self, unparsable_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [unparsable_dir])
        answer = result.get("final_answer") or {}
        assert answer.get("status") in VALID_STATUSES

    def test_confidence_is_not_one(self, unparsable_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [unparsable_dir])
        answer = result.get("final_answer") or {}
        assert answer.get("overall_confidence") != 1.0

    def test_no_documents_are_drafted(self, unparsable_dir: str) -> None:
        result = run_workflow(QUERY_WITH_RETURN_WORD, [unparsable_dir])
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}
        assert not (FORBIDDEN_ACTIONS & ids)


class TestRealEvidenceStillWorks:
    """Control: a populated case must keep behaving like a normal analysis."""

    def test_sample_case_is_unaffected(self) -> None:
        sample = Path(__file__).resolve().parent.parent / "sample_data" / "laptop_return_case"
        result = run_workflow(QUERY_WITH_RETURN_WORD, [str(sample)])
        answer = result.get("final_answer") or {}
        assert answer.get("status") == "complete"
        assert answer.get("key_facts"), "a populated case must still surface key facts"
