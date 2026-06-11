"""
Action Agent - generates actionable outputs: email drafts, checklists, watch tasks.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from agent.state import (
    AgentMessage,
    Claim,
    ClaimType,
    PendingAction,
    TaskStatus,
)


def run_action_agent(state: dict) -> dict:
    """Generate action items based on verified claims."""
    verified = state.get("verified_claims", [])
    unsupported = state.get("unsupported_claims", [])
    intent = state.get("intent", "")

    pending_actions: list[PendingAction] = []

    if "warranty" in intent or "return" in intent:
        # Generate warranty/return recommendation
        has_warranty = any("warranty" in c.text.lower() and "year" in c.text.lower() for c in verified)
        has_return = any("return" in c.text.lower() for c in verified)

        if has_warranty:
            pending_actions.append(
                PendingAction(
                    action_id="act_warranty_claim",
                    action_type="draft_email",
                    description="Draft warranty claim email to merchant/manufacturer",
                    payload={
                        "subject": "Warranty Claim Request",
                        "body": "To Whom It May Concern,\n\nI am writing to request a warranty claim for a product purchased recently. Please find the details below.\n\n[Please attach receipt and photos]\n\nThank you,\n[Your Name]",
                        "include_receipt": True,
                        "include_photos_of_issue": True,
                    },
                    requires_approval=False,
                )
            )
        if has_return:
            pending_actions.append(
                PendingAction(
                    action_id="act_return_request",
                    action_type="draft_email",
                    description="Draft return/refund request to merchant",
                    payload={
                        "subject": "Return Request",
                        "body": "To Whom It May Concern,\n\nI would like to request a return for my recent purchase. Details below.\n\n[Order details]\n\nThank you,\n[Your Name]",
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
    all_claims = verified + unsupported
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


def _build_summary(intent: str, verified: list[Claim]) -> str:
    if "warranty" in intent or "return" in intent:
        if any("warranty" in c.text.lower() and "year" in c.text.lower() for c in verified):
            return "Your product appears to be within the warranty period. You can file a warranty claim. Return window may have expired."
        return "Analysis complete. Check the key facts below for warranty/return status."
    elif "purchase" in intent:
        return "Purchase recommendation based on reviews, price, and risk analysis."
    elif "price" in intent:
        return "Price monitoring has been set up."
    return "Analysis complete."


def _calc_confidence(verified: list[Claim], unsupported: list[Claim]) -> float:
    total = len(verified) + len(unsupported)
    if total == 0:
        return 0.0
    return round(len(verified) / total, 2)
