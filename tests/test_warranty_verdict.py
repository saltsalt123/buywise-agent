"""Warranty verdict wiring: policy_agent decides it, action_agent acts on it.

Three defects stacked on this path:

1. `is_warranty_valid` was computed as `days_since <= parse_days(...) or True`, so it was
   unconditionally true and the comparison never mattered.
2. The whole block was gated on `purchase_date_str and decision.return_window_days`. A policy
   that states a warranty period but no return window — which is what the sample case looks
   like — therefore left the warranty undecided, so even the fixed comparison never ran.
3. Nothing consumed the field. action_agent used a "text mentions warranty and year"
   heuristic, so an expired warranty still produced a warranty-claim draft and a summary
   telling the user the product was within the warranty period.

These tests pin the contract at the boundary between the two agents.
"""

from __future__ import annotations

from agent.agents.action_agent import _warranty_verdict, run_action_agent
from agent.state import Claim, ClaimType


def _claim(claim_id: str, text: str, confidence: float = 0.7) -> Claim:
    return Claim(
        claim_id=claim_id, text=text, claim_type=ClaimType.POLICY_RULE, confidence=confidence
    )


def _actions_for(verified: list[Claim]) -> list[str]:
    result = run_action_agent(
        {
            "verified_claims": verified,
            "unsupported_claims": [],
            "intent": "warranty_or_return",
        }
    )
    return [action.action_id for action in result["pending_actions"]]


def _summary_for(verified: list[Claim]) -> str:
    result = run_action_agent(
        {
            "verified_claims": verified,
            "unsupported_claims": [],
            "intent": "warranty_or_return",
        }
    )
    return result["final_answer"]["summary"]


class TestWarrantyVerdict:
    def test_expired_verdict_is_detected(self):
        claims = [_claim("policy_warranty_expired", "Warranty coverage has expired")]
        assert _warranty_verdict(claims) is False

    def test_valid_verdict_is_detected(self):
        claims = [_claim("policy_warranty_valid", "Warranty coverage is still valid")]
        assert _warranty_verdict(claims) is True

    def test_absent_verdict_is_undetermined(self):
        claims = [_claim("policy_warranty_period", "Warranty period: 1 year")]
        assert _warranty_verdict(claims) is None

    def test_expired_wins_if_both_appear(self):
        claims = [
            _claim("policy_warranty_valid", "Warranty coverage is still valid"),
            _claim("policy_warranty_expired", "Warranty coverage has expired"),
        ]
        assert _warranty_verdict(claims) is False


class TestActionAgentHonoursVerdict:
    def test_expired_warranty_drafts_no_claim(self):
        actions = _actions_for([_claim("policy_warranty_expired", "Warranty coverage has expired")])
        assert "act_warranty_claim" not in actions

    def test_expired_warranty_still_offers_the_checklist(self):
        actions = _actions_for([_claim("policy_warranty_expired", "Warranty coverage has expired")])
        assert "act_checklist" in actions

    def test_valid_warranty_drafts_a_claim(self):
        claims = [_claim("policy_warranty_valid", "Warranty coverage is still valid")]
        actions = _actions_for(claims)
        assert "act_warranty_claim" in actions

    def test_absent_verdict_falls_back_to_text_heuristic(self):
        """Backwards compatible: without a verdict, behaviour is what it always was."""
        actions = _actions_for([_claim("policy_warranty_period", "Warranty period: 1 year")])
        assert "act_warranty_claim" in actions

    def test_expired_summary_does_not_claim_coverage(self):
        summary = _summary_for([_claim("policy_warranty_expired", "Warranty coverage has expired")])
        assert "expired" in summary.lower()
        assert "within the warranty period" not in summary.lower()
