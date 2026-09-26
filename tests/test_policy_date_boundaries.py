"""Date-boundary matrix for the return-window and warranty verdicts.

``test_policy_timezone_boundary.py`` pins the UTC-vs-Beijing defect.  This file walks the
calendar: the purchase day itself, the last valid day, the first expired day, the warranty
boundary, and the two cases where naive date arithmetic goes wrong — a window that crosses
New Year, and one that contains 29 February.

Every case injects the clock through ``policy_agent_now`` and works in
``Asia/Shanghai``; nothing here reads the real current time, and the module asserts that
``datetime.utcnow()`` has not crept back in.
"""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import agent.agents.policy_agent as pa
from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk

SHANGHAI = ZoneInfo("Asia/Shanghai")
POLICY_AGENT_SOURCE = Path(pa.__file__)

DEFAULT_WINDOW = 14
DEFAULT_WARRANTY = "1 year"


def _verdict(
    monkeypatch,
    purchase: date,
    now: datetime,
    window_days: int = DEFAULT_WINDOW,
    warranty: str = DEFAULT_WARRANTY,
) -> set[str]:
    """Run the real policy agent at a fixed instant; return the claim ids it published."""
    monkeypatch.setattr(pa, "policy_agent_now", lambda: now, raising=False)

    text = (
        f"Return Policy: {window_days} days from purchase date\n"
        f"Warranty: {warranty}"
    )
    chunk = EvidenceChunk(
        chunk_id="c1", source_id="s1", text=text, metadata={"doc_type": "receipt"}
    )
    order_msg = AgentMessage(
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
    out = pa.run_policy_agent({"retrieved_evidence": [chunk], "agent_messages": [order_msg]})
    return {c.claim_id for c in out["agent_messages"][-1].claims}


def _at(day: date, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SHANGHAI)


def _last_valid(purchase: date, days: int) -> date:
    return purchase + timedelta(days=days)


# ── the calendar arithmetic the module must not get wrong ───────────────────

CALENDAR_CASES = [
    # (label, purchase, window days, hard-coded last valid day)
    ("plain", date(2026, 5, 15), 14, date(2026, 5, 29)),
    ("crosses_new_year", date(2026, 12, 20), 14, date(2027, 1, 3)),
    ("leap_year_includes_feb_29", date(2024, 2, 24), 14, date(2024, 3, 9)),
    ("non_leap_year_same_month", date(2023, 2, 24), 14, date(2023, 3, 10)),
    ("leap_day_purchase", date(2024, 2, 29), 14, date(2024, 3, 14)),
    ("long_window_crosses_year", date(2026, 12, 15), 90, date(2027, 3, 15)),
]


class TestCalendarMatrix:
    @pytest.mark.parametrize(
        "label,purchase,window,expected_last",
        CALENDAR_CASES,
        ids=[c[0] for c in CALENDAR_CASES],
    )
    def test_last_valid_day_is_open(
        self, monkeypatch, label, purchase, window, expected_last
    ) -> None:
        assert _last_valid(purchase, window) == expected_last, "test setup is wrong"
        ids = _verdict(monkeypatch, purchase, _at(expected_last, 23, 59), window_days=window)
        assert "policy_return_valid" in ids, f"{label}: {expected_last} should still be open"

    @pytest.mark.parametrize(
        "label,purchase,window,expected_last",
        CALENDAR_CASES,
        ids=[c[0] for c in CALENDAR_CASES],
    )
    def test_first_expired_day_is_closed(
        self, monkeypatch, label, purchase, window, expected_last
    ) -> None:
        first_closed = expected_last + timedelta(days=1)
        ids = _verdict(monkeypatch, purchase, _at(first_closed, 0, 0), window_days=window)
        assert "policy_return_expired" in ids, f"{label}: {first_closed} should be closed"


class TestPurchaseDayAndBoundaries:
    def test_purchase_day_itself_is_within(self, monkeypatch) -> None:
        purchase = date(2026, 5, 15)
        for hour in (0, 12, 23):
            ids = _verdict(monkeypatch, purchase, _at(purchase, hour, 0))
            assert "policy_return_valid" in ids, f"hour {hour} of the purchase day"

    def test_one_minute_after_the_window_closes(self, monkeypatch) -> None:
        purchase = date(2026, 5, 15)
        last = _last_valid(purchase, 14)
        assert "policy_return_valid" in _verdict(monkeypatch, purchase, _at(last, 23, 59))
        assert "policy_return_expired" in _verdict(
            monkeypatch, purchase, _at(last + timedelta(days=1), 0, 0)
        )

    def test_a_zero_day_window_is_recorded_and_refuses_the_return(self, monkeypatch) -> None:
        """A "0 days" window is final sale stated in numbers, not a missing value.

        This test used to pin the opposite: the window claim was absent entirely because the
        policy agent guarded on ``if decision.return_window_days:`` and ``0`` is falsy. Fixed
        in the zero-day round — the window is now recorded as 0, the verdict is "expired", and
        an explicit "returns unavailable" claim is published. The warranty is unaffected.
        """
        purchase = date(2026, 5, 15)
        ids = _verdict(monkeypatch, purchase, _at(purchase), window_days=0)
        assert "policy_return_window" in ids, "the zero-day window was dropped again"
        assert "policy_return_expired" in ids, "a zero-day window left the return open"
        assert "policy_return_unavailable" in ids
        assert "policy_warranty_valid" in ids, "the warranty decision is unaffected"


class TestWarrantyBoundaries:
    def test_warranty_last_valid_day(self, monkeypatch) -> None:
        purchase = date(2026, 5, 15)
        last = purchase + timedelta(days=365)
        assert last == date(2027, 5, 15)
        ids = _verdict(monkeypatch, purchase, _at(last, 23, 59))
        assert "policy_warranty_valid" in ids

    def test_warranty_day_after_is_expired(self, monkeypatch) -> None:
        purchase = date(2026, 5, 15)
        after = purchase + timedelta(days=366)
        ids = _verdict(monkeypatch, purchase, _at(after, 0, 0))
        assert "policy_warranty_expired" in ids

    def test_warranty_crosses_new_year(self, monkeypatch) -> None:
        purchase = date(2026, 12, 20)
        last = purchase + timedelta(days=365)
        assert last == date(2027, 12, 20)
        assert "policy_warranty_valid" in _verdict(monkeypatch, purchase, _at(last))
        assert "policy_warranty_expired" in _verdict(
            monkeypatch, purchase, _at(last + timedelta(days=1))
        )

    def test_warranty_from_a_leap_day(self, monkeypatch) -> None:
        """A fixed 365-day period from 29 Feb lands on 28 Feb, not on the same day next year."""
        purchase = date(2024, 2, 29)
        last = purchase + timedelta(days=365)
        assert last == date(2025, 2, 28)
        assert "policy_warranty_valid" in _verdict(monkeypatch, purchase, _at(last, 23, 59))
        assert "policy_warranty_expired" in _verdict(
            monkeypatch, purchase, _at(last + timedelta(days=1))
        )

    def test_return_and_warranty_are_judged_independently(self, monkeypatch) -> None:
        """A long-closed return window must not suppress a live warranty."""
        purchase = date(2026, 5, 15)
        ids = _verdict(monkeypatch, purchase, _at(date(2026, 6, 30)), window_days=14)
        assert "policy_return_expired" in ids
        assert "policy_warranty_valid" in ids


class TestClockHandling:
    def test_module_does_not_call_utcnow(self) -> None:
        """Checked on the syntax tree, not the text: the module comment mentions utcnow.

        A grep would match the comment explaining the defect, so the assertion walks the AST
        and looks for an actual attribute access — a call the interpreter would perform.
        """
        tree = ast.parse(POLICY_AGENT_SOURCE.read_text())
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "utcnow"
        ]
        assert not offenders, (
            f"utcnow() re-entered policy_agent at line(s) {offenders}; the day boundary "
            "must come from policy_agent_now() / Asia-Shanghai"
        )

    def test_module_declares_a_shanghai_clock(self) -> None:
        source = POLICY_AGENT_SOURCE.read_text()
        assert "Asia/Shanghai" in source
        assert hasattr(pa, "policy_agent_now"), "the clock seam is missing"
        now = pa.policy_agent_now()
        assert now.tzinfo is not None and now.utcoffset() == timedelta(hours=8)

    def test_same_instant_in_another_label_gives_the_same_verdict(self, monkeypatch) -> None:
        purchase = date(2026, 5, 15)
        instant = _at(date(2026, 5, 30), 3, 0)
        assert instant.astimezone(timezone.utc).date() != instant.date(), "test setup"

        local = _verdict(monkeypatch, purchase, instant)
        as_utc = _verdict(monkeypatch, purchase, instant.astimezone(timezone.utc))
        assert local == as_utc

    def test_naive_clock_is_read_as_beijing(self, monkeypatch) -> None:
        purchase = date(2026, 5, 15)
        ids = _verdict(monkeypatch, purchase, datetime(2026, 5, 30, 3, 0))
        assert "policy_return_expired" in ids

    def test_no_clock_injection_still_works(self) -> None:
        """Production path: the real clock is used and returns a sane verdict."""
        chunk = EvidenceChunk(
            chunk_id="c1", source_id="s1",
            text="Return Policy: 14 days from purchase date",
            metadata={"doc_type": "receipt"},
        )
        msg = AgentMessage(
            agent_name="order_agent", status="success",
            claims=[Claim(
                claim_id="order_purchase_date",
                text=f"Purchase date: {date.today().isoformat()}",
                claim_type=ClaimType.ORDER_FACT, confidence=0.85,
            )],
        )
        out = pa.run_policy_agent({"retrieved_evidence": [chunk], "agent_messages": [msg]})
        ids = {c.claim_id for c in out["agent_messages"][-1].claims}
        assert "policy_return_valid" in ids, "today's purchase must be inside a 14-day window"
