"""A zero-day return window is a refusal, not a missing value.

``policy_agent`` guarded on ``if decision.return_window_days:`` — and ``0`` is falsy — so a
policy stating "0 days" produced *no* return-window claim and *no* verdict at all.  The
document says, in numbers, exactly what "final sale" says in words, and it was being read as
"the return window is unknown".

Expected behaviour, whichever way the document words it:

* the window is recorded as 0 days (it is not dropped);
* the return is not available, so no plain return request is drafted;
* the user is offered a human-review path instead;
* confidence is not 1.0 — a request that cannot be satisfied by the standard route is not
  something to report with full certainty.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import agent.agents.policy_agent as pa
from agent.graph import run_workflow
from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk

SHANGHAI = ZoneInfo("Asia/Shanghai")

ZERO_DAY_TEXTS = [
    "Return Policy: 0 days from purchase date",
    "Return Window: 0 days",
    "0-day return window",
]

REFUSAL_TEXTS = [
    "Return Policy: Final sale - no returns accepted",
    "Return Policy: no returns accepted on this order",
]

REVIEW_OUTCOMES = {
    "needs_human_review",
    "insufficient_evidence",
    "no_evidence",
}


def _verdict(monkeypatch, policy_text: str, purchase: date, now: datetime) -> tuple[set[str], str]:
    """Run the policy agent at a fixed instant; return (claim ids, window claim text)."""
    monkeypatch.setattr(pa, "policy_agent_now", lambda: now, raising=False)
    chunk = EvidenceChunk(
        chunk_id="c1", source_id="s1", text=policy_text, metadata={"doc_type": "policy"}
    )
    message = AgentMessage(
        agent_name="order_agent",
        status="success",
        claims=[
            Claim(
                claim_id="order_purchase_date",
                text=f"Purchase date: {purchase.isoformat()}",
                claim_type=ClaimType.ORDER_FACT,
                confidence=0.85,
            )
        ],
    )
    out = pa.run_policy_agent({"retrieved_evidence": [chunk], "agent_messages": [message]})
    claims = out["agent_messages"][-1].claims
    ids = {c.claim_id for c in claims}
    window_text = next((c.text for c in claims if c.claim_id == "policy_return_window"), "")
    return ids, window_text


class TestTheWindowIsRecordedAsZero:
    @pytest.mark.parametrize("text", ZERO_DAY_TEXTS)
    def test_a_zero_day_window_produces_a_window_claim(
        self, monkeypatch, text: str
    ) -> None:
        today = date(2026, 5, 15)
        ids, window_text = _verdict(
            monkeypatch, text, today, datetime(2026, 5, 15, 12, 0, tzinfo=SHANGHAI)
        )
        assert "policy_return_window" in ids, (
            f"{text!r} produced no return-window claim; ids={sorted(ids)}"
        )
        assert "0" in window_text, f"the zero was lost: {window_text!r}"

    @pytest.mark.parametrize("text", ZERO_DAY_TEXTS)
    def test_zero_is_not_treated_as_unresolved(self, monkeypatch, text: str) -> None:
        """The distinction under test: "0 days" is a value, not an absence of one."""
        today = date(2026, 5, 15)
        ids, _ = _verdict(
            monkeypatch, text, today, datetime(2026, 5, 15, 12, 0, tzinfo=SHANGHAI)
        )
        return_verdicts = {i for i in ids if i.startswith("policy_return")}
        assert return_verdicts, f"no return verdict at all for {text!r}: {sorted(ids)}"
        assert "policy_return_window" in ids


class TestTheWindowIsNotSatisfiable:
    @pytest.mark.parametrize("text", ZERO_DAY_TEXTS)
    def test_the_return_is_never_valid_past_the_purchase_day(
        self, monkeypatch, text: str
    ) -> None:
        purchase = date(2026, 5, 15)
        ids, _ = _verdict(
            monkeypatch, text, purchase, datetime(2026, 5, 20, 12, 0, tzinfo=SHANGHAI)
        )
        assert "policy_return_valid" not in ids, f"{text!r} left the return open"
        assert "policy_return_expired" in ids or "policy_return_unavailable" in ids

    @pytest.mark.parametrize("text", ZERO_DAY_TEXTS + REFUSAL_TEXTS)
    def test_even_on_the_purchase_day_the_return_is_not_plainly_available(
        self, monkeypatch, text: str
    ) -> None:
        """A zero-day window means the window never opened, not that it lasts until midnight."""
        purchase = date(2026, 5, 15)
        ids, _ = _verdict(
            monkeypatch, text, purchase, datetime(2026, 5, 15, 9, 0, tzinfo=SHANGHAI)
        )
        assert "policy_return_valid" not in ids, (
            f"{text!r} reported the return as valid on the purchase day"
        )


class TestWorkflowBehaviour:
    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> dict:
        target = tmp_path_factory.mktemp("zero_day") / "case"
        target.mkdir()
        purchase = (date.today() - timedelta(days=1)).isoformat()
        (target / "receipt.txt").write_text(
            "TECHWORLD INC. - SALES RECEIPT\n"
            f"Date: {purchase} 16:20:00\n"
            "Total: $1,299.00\n\n"
            "Return Policy: 0 days from purchase date\n"
        )
        return run_workflow("Can I return this laptop I bought yesterday?", [str(target)])

    def test_no_plain_return_request(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}
        assert "act_return_request" not in ids, (
            "a plain return request was drafted for a zero-day return window"
        )

    def test_an_exception_request_or_review_is_offered(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}
        assert "act_return_exception_request" in ids, (
            f"no route offered to the user; actions={sorted(ids)}"
        )

    def test_status_is_one_of_the_review_outcomes(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        assert answer.get("status") in REVIEW_OUTCOMES, answer.get("status")

    def test_confidence_is_not_certain(self, result: dict) -> None:
        answer = result.get("final_answer") or {}
        assert answer.get("overall_confidence") != 1.0, (
            "a return that cannot be made was reported with full confidence"
        )


class TestFinalSaleWording:
    @pytest.mark.parametrize("text", REFUSAL_TEXTS)
    def test_worded_refusals_also_block_the_plain_request(
        self, monkeypatch, text: str
    ) -> None:
        purchase = date(2026, 5, 15)
        ids, _ = _verdict(
            monkeypatch, text, purchase, datetime(2026, 5, 15, 9, 0, tzinfo=SHANGHAI)
        )
        assert "policy_return_valid" not in ids, f"{text!r} left the return open"
