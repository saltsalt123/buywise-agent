"""Graph-routing tests.

The MVP implements only the warranty/return flow. Any other recognised intent
must short-circuit with an explicit ``unsupported_intent`` status instead of
running the warranty pipeline and returning an answer about analysis that never
happened (the pipeline once claimed "recommendation based on reviews, price and
risk analysis" while none of those agents existed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.graph import run_workflow
from agent.state import IntentType

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"
HEADSET_CASE = str(SAMPLE_DATA / "headphone_warranty_case")
LAPTOP_CASE = str(SAMPLE_DATA / "laptop_return_case")


class TestWarrantyFlowStillRuns:
    """The implemented path must be unaffected by the short-circuit."""

    def test_warranty_query_completes(self) -> None:
        result = run_workflow(
            "My headphones stopped charging after 7 months. Can I claim warranty?",
            [HEADSET_CASE],
        )
        answer = result.get("final_answer") or {}
        assert result.get("intent") == IntentType.WARRANTY_RETURN.value
        assert answer.get("status") == "complete"
        assert answer.get("key_facts"), "warranty flow should surface key facts"


class TestUnsupportedIntentsShortCircuit:
    """Unimplemented intents must not silently return an unrelated analysis."""

    @pytest.mark.parametrize(
        "query,expected_intent",
        [
            ("Which laptop should I buy?", IntentType.PURCHASE_DECISION.value),
            ("watch for price drop on this monitor", IntentType.PRICE_MONITOR.value),
            ("Tell me a joke", IntentType.GENERAL_QA.value),
        ],
    )
    def test_returns_unsupported_intent(self, query: str, expected_intent: str) -> None:
        result = run_workflow(query, [LAPTOP_CASE])
        answer = result.get("final_answer") or {}
        assert result.get("intent") == expected_intent
        assert answer.get("status") == "unsupported_intent"
        # Nothing was retrieved and nothing was recommended.
        assert not answer.get("key_facts")
        assert not answer.get("actions")
