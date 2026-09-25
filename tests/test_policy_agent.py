"""Warranty-validity checks.

`is_warranty_valid` used to be computed as:

    days_since <= parse_days(decision.warranty_period) or True

The trailing `or True` made the expression unconditionally true, so the comparison it
was supposed to perform never mattered: a product bought 100 days ago against a 30-day
warranty still reported warranty-valid. It was not defensive coding either — `parse_days`
cannot return None here, because `warranty_period` is only assigned when the regex has
already matched a digit.

These tests run the real policy agent and inspect the PolicyDecision it builds (rather
than re-implementing the comparison), so they would catch the bug reappearing anywhere
along that path.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import agent.agents.policy_agent as pa
from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk


@pytest.fixture
def decide(monkeypatch):
    """Run run_policy_agent for a given purchase age and policy text; return its decision."""

    held: dict = {}
    real_decision = pa.PolicyDecision

    class SpyDecision(real_decision):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            held["obj"] = self

    monkeypatch.setattr(pa, "PolicyDecision", SpyDecision)

    def _run(days_ago: int, warranty_text: str):
        purchase_date = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        chunk = EvidenceChunk(
            chunk_id="c1",
            source_id="s1",
            text=f"Return Policy: 30 days from delivery. {warranty_text}",
            metadata={"doc_type": "warranty"},
        )
        claim = Claim(
            claim_id="k1",
            text=f"Purchase date: {purchase_date}",
            claim_type=ClaimType.POLICY_RULE,
            confidence=0.9,
        )
        message = AgentMessage(agent_name="order_agent", status="success", claims=[claim])
        pa.run_policy_agent({"retrieved_evidence": [chunk], "agent_messages": [message]})
        return held["obj"]

    return _run


class TestWarrantyValidity:
    def test_expired_warranty_is_reported_invalid(self, decide):
        """The bug case: 100 days old against a 30-day warranty is not valid."""
        decision = decide(100, "Warranty: 30 days limited warranty")
        assert decision.is_warranty_valid is False

    def test_active_warranty_is_reported_valid(self, decide):
        decision = decide(10, "Warranty: 30 days limited warranty")
        assert decision.is_warranty_valid is True

    def test_longer_warranty_outlives_the_return_window(self, decide):
        """A 1-year warranty should still be valid 100 days in, unlike the 30-day return window."""
        decision = decide(100, "Warranty: 1 year manufacturer warranty")
        assert decision.is_warranty_valid is True
        assert decision.is_return_valid is False

    def test_warranty_verdict_agrees_with_return_verdict_when_periods_match(self, decide):
        """Identical periods and identical dates must not disagree."""
        decision = decide(100, "Warranty: 30 days limited warranty")
        assert decision.is_return_valid is False
        assert decision.is_warranty_valid == decision.is_return_valid

    def test_missing_warranty_period_stays_undetermined(self, decide):
        """No parseable period means unknown, not valid."""
        decision = decide(100, "Warranty: see enclosed documentation")
        assert decision.warranty_period is None
        assert decision.is_warranty_valid is None
