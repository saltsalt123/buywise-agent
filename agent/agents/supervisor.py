"""
Supervisor Agent - intent classification and task planning.
"""
from __future__ import annotations

import re

from agent.state import AgentMessage, Claim, ClaimType, IntentType


def classify_intent(query: str) -> str:
    """Classify user query intent based on keywords."""
    q = query.lower()

    # Warranty / return / refund keywords
    if any(kw in q for kw in ["warranty", "return", "refund", "broken", "defect", "repair", "replace", "damage", "faulty", "stop working", "not working", "charge"]):
        return IntentType.WARRANTY_RETURN.value

    # Purchase decision keywords
    if any(kw in q for kw in ["buy", "purchase", "which one", "recommend", "best", "compare", "between", "alternative", "worth", "vs"]):
        return IntentType.PURCHASE_DECISION.value

    # Price monitor keywords
    if any(kw in q for kw in ["price", "drop", "monitor", "watch", "track", "notify", "alert", "deal", "discount", "sale"]):
        return IntentType.PRICE_MONITOR.value

    return IntentType.GENERAL_QA.value


def run_supervisor(state: dict) -> dict:
    """Supervisor node: classify intent and create execution plan."""
    query = state.get("user_query", "")
    uploaded_ids = state.get("uploaded_source_ids", [])

    intent = classify_intent(query)
    plan = {"intent": intent, "agents_needed": [], "steps": []}

    if intent == IntentType.WARRANTY_RETURN.value:
        plan["agents_needed"] = ["order_agent", "policy_agent", "product_agent", "verifier_agent", "action_agent"]
        plan["steps"] = [
            "extract_order_facts",
            "analyze_policy",
            "check_product_compatibility",
            "verify_evidence",
            "generate_actions",
        ]
    elif intent == IntentType.PURCHASE_DECISION.value:
        plan["agents_needed"] = ["product_agent", "review_agent", "price_agent", "risk_agent", "verifier_agent"]
        plan["steps"] = [
            "extract_product_facts",
            "summarize_reviews",
            "check_price",
            "assess_risks",
            "make_recommendation",
        ]
    elif intent == IntentType.PRICE_MONITOR.value:
        plan["agents_needed"] = ["price_agent", "policy_agent", "action_agent"]
        plan["steps"] = [
            "check_current_price",
            "analyze_return_policy",
            "setup_watch",
        ]
    else:
        plan["agents_needed"] = ["order_agent"]
        plan["steps"] = ["answer_general"]

    message = AgentMessage(
        agent_name="supervisor",
        status="success",
        claims=[
            Claim(
                claim_id="intent_classified",
                text=f"Intent classified as: {intent}",
                claim_type=ClaimType.ORDER_FACT,
                confidence=0.9,
            )
        ],
        evidence_ids=uploaded_ids,
        confidence=0.9,
        next_actions=plan["agents_needed"],
    )

    return {
        **state,
        "intent": intent,
        "plan": plan,
        "agent_messages": [message],
    }
