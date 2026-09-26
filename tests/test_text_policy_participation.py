"""A plain-text policy must take part in the analysis.

Supersedes the older ``test_zero_evidence_behavior.py`` finding that a ``.txt`` file could
not be seen at all: ``return_policy.txt`` was inferred as ``manual``, and ``policy_agent``
only reads ``{warranty, policy, receipt}``, so the policy was dropped from every decision
while the run still reported success.

The receipt carries a recent purchase date so the window is *open*: if the run reacts by
refusing the return, it must be because of the policy, not because the window expired.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from agent.graph import _load_sample_data, run_workflow

QUERY = "Can I return this laptop I bought last week?"

POLICY_TXT = (
    "TechWorld Return Policy\n"
    "-----------------------\n"
    "Return Window: 14 days from delivery\n"
    "Condition: item must be unused and in its original packaging\n"
    "Final sale - no returns accepted on clearance items\n"
    "Refund: no refunds are available for clearance purchases\n"
)


def _receipt(days_ago: int = 5, window: int = 30) -> str:
    purchase = (date.today() - timedelta(days=days_ago)).isoformat()
    return (
        "TECHWORLD INC. - SALES RECEIPT\n"
        f"Date: {purchase} 16:20:00\n"
        'Item: PowerBook Pro 15"\n'
        "Total: $1,299.00\n\n"
        f"Return Policy: {window} days from purchase date\n"
    )


@pytest.fixture()
def case_dir(tmp_path: Path) -> Path:
    target = tmp_path / "txt_policy_case"
    target.mkdir()
    (target / "receipt.txt").write_text(_receipt())
    (target / "return_policy.txt").write_text(POLICY_TXT)
    return target


class TestTheTxtPolicyIsIngested:
    def test_policy_txt_becomes_a_policy_chunk(self, case_dir: Path) -> None:
        chunks = _load_sample_data([str(case_dir)])
        by_type: dict[str, list[str]] = {}
        for chunk in chunks:
            by_type.setdefault(str(chunk.metadata.get("doc_type")), []).append(chunk.text)

        assert "policy" in by_type, (
            f"the .txt policy was not classified as a policy; types seen: {sorted(by_type)}"
        )
        policy_text = " ".join(by_type["policy"])
        assert "Return Window: 14 days" in policy_text
        assert "Final sale" in policy_text

    def test_policy_txt_is_in_the_set_the_policy_agent_reads(self, case_dir: Path) -> None:
        chunks = _load_sample_data([str(case_dir)])
        readable = {"warranty", "policy", "receipt"}
        policy_chunks = [c for c in chunks if "Final sale" in c.text]
        assert policy_chunks, "the .txt policy text is not in the index at all"
        for chunk in policy_chunks:
            assert chunk.metadata.get("doc_type") in readable, (
                f"doc_type={chunk.metadata.get('doc_type')!r} is not read by the policy agent"
            )


class TestTheTxtPolicyReachesTheAnswer:
    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> dict:
        target = tmp_path_factory.mktemp("txt_policy_run") / "case"
        target.mkdir()
        (target / "receipt.txt").write_text(_receipt())
        (target / "return_policy.txt").write_text(POLICY_TXT)
        return run_workflow(QUERY, [str(target)])

    def test_the_policy_is_retrieved(self, result: dict) -> None:
        texts = " ".join(c.text for c in result.get("retrieved_evidence", []))
        assert "Final sale" in texts, "the .txt policy never reached the retriever"

    def test_the_conflict_is_detected(self, result: dict) -> None:
        ids = {c.claim_id for c in result.get("verified_claims", [])}
        assert "policy_return_conflict" in ids, (
            f"the receipt grants a window and the policy refuses returns, but no conflict was "
            f"recorded; verified claims were {sorted(ids)}"
        )

    def test_status_asks_for_a_human(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        assert answer.get("status") == "needs_human_review", answer.get("status")

    def test_no_plain_return_request_is_drafted(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}
        assert "act_return_request" not in ids, (
            "a plain return request was drafted despite a final-sale policy"
        )

    def test_an_exception_request_is_offered(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}
        assert "act_return_exception_request" in ids

    def test_confidence_is_not_certain(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        assert answer.get("overall_confidence") != 1.0

    def test_the_summary_does_not_pretend_the_return_is_straightforward(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        summary = str(answer.get("summary", "")).lower()
        assert any(
            w in summary for w in ("conflict", "final sale", "no returns", "disagree")
        ), summary


class TestControlStillWorks:
    def test_an_agreeing_txt_policy_does_not_raise_a_conflict(self, tmp_path: Path) -> None:
        """Without the refusal wording the same setup must stay a normal return."""
        target = tmp_path / "agreeing"
        target.mkdir()
        (target / "receipt.txt").write_text(_receipt())
        (target / "return_policy.txt").write_text(
            "Return Window: 30 days from delivery\n"
            "Refund: full refund to the original payment method\n"
        )
        result = run_workflow(QUERY, [str(target)])
        answer = result.get("final_answer") or {}
        ids = {c.claim_id for c in result.get("verified_claims", [])}
        assert "policy_return_conflict" not in ids
        assert answer.get("status") == "complete"
        assert "act_return_request" in {a.get("action_id") for a in answer.get("actions", [])}
