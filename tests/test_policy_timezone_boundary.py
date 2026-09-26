"""Return-window boundaries are decided on the Asia/Shanghai calendar, not UTC.

``policy_agent`` computed ``days_since = (datetime.utcnow() - purchase_date).days``.
Between 00:00 and 08:00 Beijing time the UTC date is still the previous day, so on the
first eight hours of every day a window that had just closed was still reported as open —
and on the day it closed, the last valid day was treated as already over.

The decision is exposed through the claim ids the policy agent publishes
(``policy_return_valid`` / ``policy_return_expired``), which is what downstream agents
read, so these tests assert on those rather than on internal attributes.

``policy_agent_now()`` is the clock seam: production code calls it, tests replace it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import agent.agents.policy_agent as pa
from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk

SHANGHAI = ZoneInfo("Asia/Shanghai")

PURCHASE_DATE = "2026-05-15"
RETURN_WINDOW_DAYS = 14

# 2026-05-15 + 14 days -> 2026-05-29 is the last day the window is open.
LAST_VALID_DAY = datetime(2026, 5, 29, 23, 59, tzinfo=SHANGHAI)
FIRST_EXPIRED_DAY = datetime(2026, 5, 30, 0, 0, tzinfo=SHANGHAI)


def _policy_claim_ids(monkeypatch, now: datetime, days: int = RETURN_WINDOW_DAYS) -> set[str]:
    """Run the real policy agent at a fixed instant and return the claim ids it published."""
    monkeypatch.setattr(pa, "policy_agent_now", lambda: now, raising=False)

    chunk = EvidenceChunk(
        chunk_id="c1",
        source_id="s1",
        text=f"Return Policy: {days} days from purchase date",
        metadata={"doc_type": "receipt"},
    )
    order_msg = AgentMessage(
        agent_name="order_agent",
        status="success",
        claims=[
            Claim(
                claim_id="order_purchase_date",
                text=f"Purchase date: {PURCHASE_DATE}",
                claim_type=ClaimType.ORDER_FACT,
                confidence=0.85,
            )
        ],
    )
    out = pa.run_policy_agent({"retrieved_evidence": [chunk], "agent_messages": [order_msg]})
    policy_message = out["agent_messages"][-1]
    return {claim.claim_id for claim in policy_message.claims}


class TestWindowBoundary:
    """Last valid day is open; the next Beijing day is closed."""

    def test_last_valid_day_is_within(self, monkeypatch) -> None:
        ids = _policy_claim_ids(monkeypatch, LAST_VALID_DAY)
        assert "policy_return_valid" in ids, (
            f"{LAST_VALID_DAY.isoformat()} is day {RETURN_WINDOW_DAYS} of a "
            f"{RETURN_WINDOW_DAYS}-day window and must count as open"
        )

    def test_first_expired_day_is_past(self, monkeypatch) -> None:
        ids = _policy_claim_ids(monkeypatch, FIRST_EXPIRED_DAY)
        assert "policy_return_expired" in ids, (
            f"{FIRST_EXPIRED_DAY.isoformat()} is day {RETURN_WINDOW_DAYS + 1} and must "
            "count as closed"
        )

    def test_purchase_day_itself_is_within(self, monkeypatch) -> None:
        ids = _policy_claim_ids(monkeypatch, datetime(2026, 5, 15, 0, 0, tzinfo=SHANGHAI))
        assert "policy_return_valid" in ids


class TestBeijingEarlyHoursAreNotJudgedByTheUtcDate:
    """The regression window: 00:00-08:00 Beijing, when the UTC date lags behind."""

    def test_closed_window_is_not_reopened_after_midnight(self, monkeypatch) -> None:
        # 2026-05-30 03:00 Beijing is still 2026-05-29 in UTC.
        ids = _policy_claim_ids(monkeypatch, datetime(2026, 5, 30, 3, 0, tzinfo=SHANGHAI))
        assert "policy_return_expired" in ids, (
            "at 03:00 Beijing the UTC date is still the previous day, which reopened a "
            "window that had already closed"
        )
        assert "policy_return_valid" not in ids

    def test_every_hour_of_the_first_beijing_morning_matches_the_day_verdict(
        self, monkeypatch
    ) -> None:
        """All eight early hours of the day the window closes must agree."""
        for hour in range(0, 8):
            ids = _policy_claim_ids(monkeypatch, datetime(2026, 5, 30, hour, 30, tzinfo=SHANGHAI))
            assert "policy_return_expired" in ids, (
                f"2026-05-30 {hour:02d}:30 Beijing was judged {sorted(ids)}"
            )


class TestEquivalentInstantsAgree:
    """The same physical instant must not change the verdict with its timezone label."""

    def test_utc_label_of_the_same_instant_gives_the_same_verdict(self, monkeypatch) -> None:
        # 03:00 Beijing is 19:00 the previous day in UTC, so the two labels carry different
        # calendar dates and any date taken from the label rather than the instant shows up.
        shanghai_instant = datetime(2026, 5, 30, 3, 0, tzinfo=SHANGHAI)
        as_utc = shanghai_instant.astimezone(timezone.utc)
        assert as_utc.date() != shanghai_instant.date(), (
            "test setup: this instant should straddle the UTC date boundary"
        )

        shanghai_ids = _policy_claim_ids(monkeypatch, shanghai_instant)
        utc_ids = _policy_claim_ids(monkeypatch, as_utc)

        assert shanghai_ids == utc_ids, (
            "the same instant produced different verdicts depending on its timezone label; "
            "the day must be taken from the Beijing calendar"
        )
        assert "policy_return_expired" in shanghai_ids


class TestNaiveTimestampsDoNotCrash:
    def test_naive_clock_value_is_treated_as_beijing(self, monkeypatch) -> None:
        """A naive timestamp must not raise; it is read as Beijing local time."""
        ids = _policy_claim_ids(monkeypatch, datetime(2026, 5, 30, 3, 0))
        assert "policy_return_expired" in ids
