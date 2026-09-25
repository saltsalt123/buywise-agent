"""Return-window verdict: parsing, and the two agents that pass it along.

The return window had the same shape of problem as the warranty verdict, plus two outright
parsing failures that meant it was never determined in either sample case:

1. The pattern required "Return Policy: 30 days" and rejected the hyphenated form the warranty
   card uses ("RETURN POLICY: 30-day return window").
2. Only `warranty`/`policy` documents were searched for policy lines, but both sample cases
   state the return window on the *receipt*.

And the verdict had no consumer: action_agent looked for the word "return" in any claim text
and always proposed a return request, even when the window had closed months earlier.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import agent.agents.policy_agent as pa
from agent.agents.action_agent import _return_verdict, run_action_agent
from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk


def _claim(claim_id: str, text: str, confidence: float = 0.7) -> Claim:
    return Claim(
        claim_id=claim_id, text=text, claim_type=ClaimType.POLICY_RULE, confidence=confidence
    )


def _actions_for(verified: list[Claim]) -> list[str]:
    result = run_action_agent(
        {"verified_claims": verified, "unsupported_claims": [], "intent": "warranty_or_return"}
    )
    return [action.action_id for action in result["pending_actions"]]


def _summary_for(verified: list[Claim]) -> str:
    result = run_action_agent(
        {"verified_claims": verified, "unsupported_claims": [], "intent": "warranty_or_return"}
    )
    return result["final_answer"]["summary"]


def _decide(policy_text: str, doc_type: str, days_ago: int = 10):
    """Run the real policy agent over one chunk and return the decision it built."""
    held: dict = {}
    real_decision = pa.PolicyDecision

    class SpyDecision(real_decision):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            held["obj"] = self

    original = pa.PolicyDecision
    pa.PolicyDecision = SpyDecision
    try:
        purchase_date = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        chunk = EvidenceChunk(
            chunk_id="c1",
            source_id="s1",
            text=policy_text,
            metadata={"doc_type": doc_type},
        )
        msg = AgentMessage(
            agent_name="order_agent",
            status="success",
            claims=[
                Claim(
                    claim_id="k1",
                    text=f"Purchase date: {purchase_date}",
                    claim_type=ClaimType.POLICY_RULE,
                    confidence=0.9,
                )
            ],
        )
        pa.run_policy_agent({"retrieved_evidence": [chunk], "agent_messages": [msg]})
    finally:
        pa.PolicyDecision = original
    return held["obj"]


class TestReturnWindowParsing:
    def test_plain_form_is_parsed(self):
        decision = _decide("Return Policy: 30 days from purchase date", "receipt")
        assert decision.return_window_days == 30

    def test_hyphenated_form_is_parsed(self):
        """The warranty card writes "30-day", which the original pattern rejected."""
        decision = _decide("RETURN POLICY: 30-day return window from purchase date", "warranty")
        assert decision.return_window_days == 30

    def test_receipt_counts_as_a_policy_source(self):
        """Both sample cases state the return window on the receipt."""
        decision = _decide("Return Policy: 14 days for laptops (unopened)", "receipt")
        assert decision.return_window_days == 14

    def test_window_is_evaluated_against_the_purchase_date(self):
        decision = _decide("Return Policy: 30 days from purchase date", "receipt", days_ago=100)
        assert decision.is_return_valid is False

    def test_window_still_open(self):
        decision = _decide("Return Policy: 30 days from purchase date", "receipt", days_ago=5)
        assert decision.is_return_valid is True


class TestReturnVerdict:
    def test_expired_verdict_is_detected(self):
        claimants = [_claim("policy_return_expired", "The return window has closed")]
        assert _return_verdict(claimants) is False

    def test_open_verdict_is_detected(self):
        claimants = [_claim("policy_return_valid", "The return window is still open")]
        assert _return_verdict(claimants) is True

    def test_absent_verdict_is_undetermined(self):
        claimants = [_claim("policy_return_window", "Return window: 30 days (past window)")]
        assert _return_verdict(claimants) is None


class TestActionAgentHonoursReturnVerdict:
    def test_closed_window_does_not_draft_a_plain_return(self):
        actions = _actions_for([_claim("policy_return_expired", "The return window has closed")])
        assert "act_return_request" not in actions

    def test_closed_window_offers_an_exception_request_instead(self):
        """Dropping the action entirely would leave the user with nothing to do."""
        actions = _actions_for([_claim("policy_return_expired", "The return window has closed")])
        assert "act_return_exception_request" in actions

    def test_open_window_drafts_a_return(self):
        actions = _actions_for([_claim("policy_return_valid", "The return window is still open")])
        assert "act_return_request" in actions

    def test_absent_verdict_falls_back_to_text_heuristic(self):
        actions = _actions_for([_claim("policy_warranty_period", "Return window: 30 days")])
        assert "act_return_request" in actions

    def test_summary_reports_the_closed_window(self):
        summary = _summary_for(
            [_claim("policy_return_expired", "The return window has closed")]
        )
        assert "return window has closed" in summary.lower()


class TestSummaryDoesNotOverclaim:
    def test_no_warranty_found_is_not_reported_as_expired(self):
        """A missing warranty period means unknown, and must not be worded as expired.

        The text heuristic returns a bool, and reading its False as "warranty expired" produced
        a summary asserting a lapse the documents never mentioned.
        """
        summary = _summary_for([_claim("policy_return_expired", "The return window has closed")])
        assert "warranty coverage has expired" not in summary.lower()
        assert "no warranty period was found" in summary.lower()

    def test_expired_verdict_is_reported_as_expired(self):
        summary = _summary_for(
            [
                _claim("policy_return_expired", "The return window has closed"),
                _claim("policy_warranty_expired", "Warranty coverage has expired"),
            ]
        )
        assert "warranty coverage has expired" in summary.lower()
