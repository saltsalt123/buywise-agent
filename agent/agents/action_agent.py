"""
Action Agent - generates actionable outputs: email drafts, checklists, watch tasks.
"""
from __future__ import annotations

from datetime import datetime

from agent.state import (
    AgentMessage,
    Claim,
    ClaimType,
    PendingAction,
)


def run_action_agent(state: dict) -> dict:
    """Generate action items based on verified claims."""
    verified = state.get("verified_claims", [])
    unsupported = state.get("unsupported_claims", [])
    intent = state.get("intent", "")

    pending_actions: list[PendingAction] = []

    if "warranty" in intent or "return" in intent:
        # Generate warranty/return recommendation. A warranty the policy agent has already
        # ruled expired is not worth drafting a claim for. Fall back to the old text heuristic
        # only when no verdict exists — no purchase date, or no stated warranty period.
        warranty_verdict = _warranty_verdict(verified)
        if warranty_verdict is None:
            warranty_verdict = any(
                "warranty" in c.text.lower() and "year" in c.text.lower() for c in verified
            )
        has_warranty = warranty_verdict

        # Same treatment for returns, but a closed window still leaves the user something to
        # do: ask for an exception. Keeping the raw verdict lets the branch below tell
        # "closed" apart from "unknown".
        return_verdict = _return_verdict(verified)
        has_return = (
            return_verdict
            if return_verdict is not None
            else any("return" in c.text.lower() for c in verified)
        )

        if has_warranty:
            pending_actions.append(
                PendingAction(
                    action_id="act_warranty_claim",
                    action_type="draft_email",
                    description="Draft warranty claim email to merchant/manufacturer",
                    payload={
                        "subject": "Warranty Claim Request",
                        "body": (
                            "To Whom It May Concern,\n\n"
                            "I am writing to request a warranty claim for a product "
                            "purchased recently. Please find the details below.\n\n"
                            "[Please attach receipt and photos]\n\n"
                            "Thank you,\n"
                            "[Your Name]"
                        ),
                        "include_receipt": True,
                        "include_photos_of_issue": True,
                    },
                    requires_approval=False,
                )
            )
        if return_verdict is False:
            # A plain return request would misrepresent the situation, but merchants do grant
            # exceptions, so offer that rather than dropping the action entirely.
            pending_actions.append(
                PendingAction(
                    action_id="act_return_exception_request",
                    action_type="draft_email",
                    description=(
                        "Draft an exception request — the return window has closed, so ask "
                        "whether an exception is possible"
                    ),
                    payload={
                        "subject": "Return Exception Request",
                        "body": (
                            "To Whom It May Concern,\n\n"
                            "I would like to ask whether an exception can be made for a return. "
                            "I understand the standard return window has closed, and I would "
                            "appreciate it if you could consider my situation.\n\n"
                            "[Order details]\n\n"
                            "Thank you,\n"
                            "[Your Name]"
                        ),
                        "include_order_number": True,
                    },
                    requires_approval=False,
                )
            )
        elif has_return:
            pending_actions.append(
                PendingAction(
                    action_id="act_return_request",
                    action_type="draft_email",
                    description="Draft return/refund request to merchant",
                    payload={
                        "subject": "Return Request",
                        "body": (
                            "To Whom It May Concern,\n\n"
                            "I would like to request a return for my recent purchase. "
                            "Details below.\n\n"
                            "[Order details]\n\n"
                            "Thank you,\n"
                            "[Your Name]"
                        ),
                        "include_order_number": True,
                    },
                    requires_approval=False,
                )
            )

        # Checklist items
        pending_actions.append(
            PendingAction(
                action_id="act_checklist",
                action_type="export_report",
                description="Collect these items before contacting support:",
                payload={
                    "checklist": [
                        "Order number / receipt",
                        "Photos of the issue",
                        "Product serial number",
                        "Warranty card or proof of purchase",
                    ]
                },
                requires_approval=False,
            )
        )

    elif "price" in intent or "monitor" in intent:
        pending_actions.append(
            PendingAction(
                action_id="act_price_watch",
                action_type="create_watch",
                description="Create price drop alert (mock)",
                payload={
                    "watch_type": "price_drop",
                    "threshold_pct": 20,
                    "check_interval": "daily",
                    "created_at": datetime.utcnow().isoformat(),
                },
                requires_approval=True,
            )
        )

    claims = []
    if pending_actions:
        actions_desc = "; ".join(a.description for a in pending_actions[:3])
        claims.append(
            Claim(
                claim_id="action_items",
                text=f"Generated {len(pending_actions)} action(s): {actions_desc}",
                claim_type=ClaimType.ACTION,
                confidence=0.85,
            )
        )

    message = AgentMessage(
        agent_name="action_agent",
        status="success",
        claims=claims,
        confidence=0.85,
        next_actions=[],
    )

    # Build final answer
    final_answer = {
        "summary": _build_summary(intent, verified),
        "key_facts": [
            {"text": c.text, "confidence": c.confidence, "supported": c.supported_by != []}
            for c in verified[:5]
        ],
        "uncertainties": [
            {"text": c.text, "reason": c.uncertainty}
            for c in unsupported
            if c.uncertainty
        ],
        "actions": [
            {
                "action_id": a.action_id,
                "type": a.action_type,
                "description": a.description,
                "requires_approval": a.requires_approval,
            }
            for a in pending_actions
        ],
        "overall_confidence": _calc_confidence(verified, unsupported),
    }

    return {
        **state,
        "agent_messages": state.get("agent_messages", []) + [message],
        "pending_actions": pending_actions,
        "final_answer": final_answer,
    }


def _return_verdict(verified: list[Claim]) -> bool | None:
    """The policy agent's return-window verdict, or None when it could not decide."""
    claim_ids = {claim.claim_id for claim in verified}
    if "policy_return_expired" in claim_ids:
        return False
    if "policy_return_valid" in claim_ids:
        return True
    return None


def _warranty_verdict(verified: list[Claim]) -> bool | None:
    """The policy agent's warranty verdict, or None when it could not decide."""
    claim_ids = {claim.claim_id for claim in verified}
    if "policy_warranty_expired" in claim_ids:
        return False
    if "policy_warranty_valid" in claim_ids:
        return True
    return None


def _build_summary(intent: str, verified: list[Claim]) -> str:
    if "warranty" in intent or "return" in intent:
        warranty_verdict = _warranty_verdict(verified)
        # A warranty being *mentioned* is not the same as it being *valid*: the text heuristic
        # only says a period was written down somewhere, so it must not be read as "expired"
        # when it comes back false.
        warranty_mentioned = any(
            "warranty" in c.text.lower() and "year" in c.text.lower() for c in verified
        )
        returns = _return_verdict(verified)

        if warranty_verdict is False:
            if returns is True:
                return (
                    "Warranty coverage has expired, but the return window is still open — "
                    "request a return rather than a warranty claim."
                )
            return (
                "Warranty coverage has expired for this purchase, so a warranty claim is "
                "unlikely to succeed. Check the return window and any extended coverage."
            )
        if warranty_verdict is True or warranty_mentioned:
            if returns is False:
                return (
                    "Your product is still within its warranty period, but the return window "
                    "has closed. A warranty claim is the remaining option."
                )
            return (
                "Your product appears to be within the warranty period. "
                "You can file a warranty claim. Return window may have expired."
            )
        if returns is False:
            return (
                "The return window has closed and no warranty period was found in the "
                "documents. Check for extended coverage or contact support."
            )
        return "Analysis complete. Check the key facts below for warranty/return status."
    elif "purchase" in intent:
        return "Purchase-decision analysis is not implemented in this MVP."
    elif "price" in intent:
        return "Price monitoring is not implemented in this MVP."
    return "Analysis complete."


def _calc_confidence(verified: list[Claim], unsupported: list[Claim]) -> float:
    total = len(verified) + len(unsupported)
    if total == 0:
        return 0.0
    return round(len(verified) / total, 2)
