"""The wordings merchants actually use to refuse a return.

The refusal list started with the handful of phrases in the first fixture.  Everything else
— "all sales are final", "not eligible for return", "clearance items cannot be returned",
"exchange only" — was invisible, so a policy that plainly refuses a return was read as a
policy that says nothing about returns, and the standard return path was taken.

Each phrase below is a real refusal.  Tested at two levels: the policy agent must record it,
and the workflow must not draft a plain return request.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import agent.agents.policy_agent as pa
from agent.graph import run_workflow
from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk

SHANGHAI = ZoneInfo("Asia/Shanghai")

# (label, refusal wording) — the label keeps the parametrised ids readable.
REFUSALS = [
    ("all_sales_are_final", "All sales are final."),
    ("non_returnable", "This item is non-returnable."),
    ("returns_not_accepted", "Returns are not accepted."),
    ("not_eligible", "Not eligible for return."),
    ("clearance_cannot_be_returned", "Clearance items cannot be returned."),
    ("exchange_only", "Exchange only."),
    ("refunds_unavailable", "Refunds are unavailable."),
    # the original pattern, kept so it cannot regress
    ("final_sale", "This item is final sale."),
]

# A window in the same document: without one there is nothing to conflict with, and the
# refusal alone is still a refusal.
WINDOW_LINE = "Return Window: 14 days from delivery\n"

CONFLICT_OR_UNAVAILABLE = {"policy_return_conflict", "policy_return_unavailable"}
FORBIDDEN_ACTION = "act_return_request"


def _policy_claims(
    monkeypatch, text: str, purchase: date, now: datetime
) -> list[Claim]:
    monkeypatch.setattr(pa, "policy_agent_now", lambda: now, raising=False)
    chunk = EvidenceChunk(
        chunk_id="c1", source_id="s1", text=text, metadata={"doc_type": "policy"}
    )
    order = AgentMessage(
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
    out = pa.run_policy_agent({"retrieved_evidence": [chunk], "agent_messages": [order]})
    return out["agent_messages"][-1].claims


class TestRefusalIsRecorded:
    @pytest.mark.parametrize("label,wording", REFUSALS, ids=[r[0] for r in REFUSALS])
    def test_refusal_produces_a_conflict_or_unavailable_claim(
        self, monkeypatch, label: str, wording: str
    ) -> None:
        purchase = date(2026, 5, 15)
        claims = _policy_claims(
            monkeypatch,
            WINDOW_LINE + wording,
            purchase,
            datetime(2026, 5, 15, 9, 0, tzinfo=SHANGHAI),
        )
        ids = {c.claim_id for c in claims}
        assert ids & CONFLICT_OR_UNAVAILABLE, (
            f"{wording!r} was not recognised as a refusal; claims were {sorted(ids)}"
        )

    @pytest.mark.parametrize("label,wording", REFUSALS, ids=[r[0] for r in REFUSALS])
    def test_refusal_alone_is_still_a_refusal(
        self, monkeypatch, label: str, wording: str
    ) -> None:
        """No stated window: the document still refuses a return."""
        purchase = date(2026, 5, 15)
        claims = _policy_claims(
            monkeypatch, wording, purchase, datetime(2026, 5, 15, 9, 0, tzinfo=SHANGHAI)
        )
        ids = {c.claim_id for c in claims}
        assert ids & CONFLICT_OR_UNAVAILABLE, (
            f"{wording!r} produced nothing; claims were {sorted(ids)}"
        )

    @pytest.mark.parametrize("label,wording", REFUSALS, ids=[r[0] for r in REFUSALS])
    def test_both_sides_are_preserved_when_the_window_is_open(
        self, monkeypatch, label: str, wording: str
    ) -> None:
        """An open window is not suppressed by a refusal, and a refusal is not hidden by it.

        Discarding the window verdict would lose the fact that the receipt grants one; the
        disagreement is carried by its own claim instead, and *that* is what stops the plain
        return request downstream. Both signals have to survive the policy agent.
        """
        purchase = date(2026, 5, 15)
        claims = _policy_claims(
            monkeypatch,
            WINDOW_LINE + wording,
            purchase,
            datetime(2026, 5, 16, 9, 0, tzinfo=SHANGHAI),
        )
        ids = {c.claim_id for c in claims}
        assert "policy_return_valid" in ids, (
            f"{wording!r}: the receipt's open window was discarded"
        )
        assert ids & CONFLICT_OR_UNAVAILABLE, (
            f"{wording!r}: the refusal was dropped, leaving an open window as the whole story"
        )


class TestWorkflowRefusesToDraft:
    @pytest.mark.parametrize("label,wording", REFUSALS, ids=[r[0] for r in REFUSALS])
    def test_no_plain_return_request_for_any_refusal(
        self, tmp_path: Path, label: str, wording: str
    ) -> None:
        target = tmp_path / f"case_{label}"
        target.mkdir()
        purchase = (date.today() - timedelta(days=3)).isoformat()
        (target / "receipt.txt").write_text(
            "TECHWORLD INC. - SALES RECEIPT\n"
            f"Date: {purchase} 16:20:00\n"
            "Total: $1,299.00\n\n"
            "Return Policy: 30 days from purchase date\n"
        )
        (target / "return_policy.txt").write_text(WINDOW_LINE + wording + "\n")

        result = run_workflow("Can I return this laptop I bought last week?", [str(target)])
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}

        assert FORBIDDEN_ACTION not in ids, (
            f"{wording!r}: a plain return request was drafted; actions={sorted(ids)}"
        )
        assert "act_return_exception_request" in ids, (
            f"{wording!r}: nothing was offered instead; actions={sorted(ids)}"
        )
        assert answer.get("status") in {"needs_human_review", "complete"}, answer.get("status")
        assert answer.get("overall_confidence") != 1.0, (
            f"{wording!r}: reported with full confidence"
        )


class TestThePatternsAreNotOvereager:
    def test_an_ordinary_policy_is_not_treated_as_a_refusal(self, monkeypatch) -> None:
        """A normal policy must still produce a plain return path."""
        purchase = date(2026, 5, 15)
        claims = _policy_claims(
            monkeypatch,
            "Return Window: 30 days from delivery\n"
            "Refund: full refund to the original payment method\n"
            "Condition: unused and in original packaging\n",
            purchase,
            datetime(2026, 5, 20, 9, 0, tzinfo=SHANGHAI),
        )
        ids = {c.claim_id for c in claims}
        assert not (ids & CONFLICT_OR_UNAVAILABLE), (
            f"an ordinary policy was read as a refusal: {sorted(ids)}"
        )
        assert "policy_return_valid" in ids

    def test_refusal_wording_in_a_manual_does_not_gate_the_return(self, tmp_path: Path) -> None:
        """Only policy/warranty/receipt chunks are read; a manual must not be consulted.

        This is the other side of the doc_type work: widening what counts as a policy must not
        widen it to manuals, or any stray phrase in a user guide would block a valid return.
        """
        purchase = (date.today() - timedelta(days=3)).isoformat()
        (tmp_path / "receipt.txt").write_text(
            "TECHWORLD INC. - SALES RECEIPT\n"
            f"Date: {purchase} 16:20:00\n"
            "Total: $1,299.00\n\n"
            "Return Policy: 30 days from purchase date\n"
        )
        (tmp_path / "user_manual.txt").write_text(
            "Chapter 5: 'final sale' is used here as a marketing term. "
            "No returns are not mentioned in this manual at all.\n"
        )

        result = run_workflow("Can I return this laptop I bought last week?", [str(tmp_path)])
        answer = result.get("final_answer") or {}
        ids = {a.get("action_id") for a in answer.get("actions", [])}

        assert answer.get("status") == "complete", (
            f"a manual was allowed to change the return verdict: {answer.get('status')}"
        )
        assert FORBIDDEN_ACTION in ids, (
            f"a valid return was suppressed by wording in a manual; actions={sorted(ids)}"
        )
