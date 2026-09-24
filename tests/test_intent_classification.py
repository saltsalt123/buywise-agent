"""Intent-classification regression tests.

These guard two bugs that shipped in this repo:

1. Warranty queries silently classified as ``general_qa``. Matching is a plain
   substring test, so an inflection whose stem is respelled never matched its
   base form: ``charging`` does not contain ``charge``, ``broke`` does not
   contain ``broken``, ``stopped working`` does not contain ``stop working``.
2. Non-warranty intents silently running the warranty pipeline and returning an
   answer about analysis that never happened (covered in test_workflow_routing).
"""

from __future__ import annotations

import pytest

from agent.agents.supervisor import classify_intent
from agent.state import IntentType


class TestIntentRouting:
    """Each intent category still routes to the right label."""

    @pytest.mark.parametrize(
        "query",
        [
            "My headphones stopped charging after 7 months. Can I claim warranty?",
            "I want to return this laptop",
            "The screen is broken",
            "my charger stopped working",
            "warranty claim please",
        ],
    )
    def test_warranty_intents(self, query: str) -> None:
        assert classify_intent(query) == IntentType.WARRANTY_RETURN.value

    @pytest.mark.parametrize(
        "query",
        [
            "Which laptop should I buy?",
            "Which monitor is best for coding?",
        ],
    )
    def test_purchase_intents(self, query: str) -> None:
        assert classify_intent(query) == IntentType.PURCHASE_DECISION.value

    @pytest.mark.parametrize(
        "query",
        [
            "watch for price drop on this monitor",
            "set a price alert",
        ],
    )
    def test_price_intents(self, query: str) -> None:
        assert classify_intent(query) == IntentType.PRICE_MONITOR.value

    @pytest.mark.parametrize(
        "query",
        [
            "Tell me a joke",
            "How do I cook pasta?",
            "What is the weather today?",
            "Explain quantum computing",
            "Hello, who are you?",
        ],
    )
    def test_general_qa_intents(self, query: str) -> None:
        assert classify_intent(query) == IntentType.GENERAL_QA.value


class TestInflectionCoverage:
    """Inflections with a respelled stem must be matched explicitly.

    Every case below used to return ``general_qa``.
    """

    @pytest.mark.parametrize(
        "query",
        [
            "my headphones stopped charging",       # charging   (stem-final e dropped)
            "my laptop broke last week",            # broke      (irregular)
            "it breaks easily",                     # breaks
            "the hinge is breaking",                # breaking
            "the battery is damaging the device",   # damaging   (stem-final e dropped)
            "there is a fault in the screen",       # fault      (faulty -> fault)
            "check my warranties",                  # warranties (y -> ies)
            "it broke on day one",
            "the charging port is loose",
            "It stopped working yesterday",         # stopped working
        ],
    )
    def test_inflections_classified_as_warranty(self, query: str) -> None:
        assert classify_intent(query) == IntentType.WARRANTY_RETURN.value

    @pytest.mark.parametrize(
        "query",
        [
            "Tell me a joke",
            "How do I cook pasta?",
            "Summarise this document",
            "What is the weather today?",
            "Explain quantum computing",
        ],
    )
    def test_no_false_positives_on_negative_controls(self, query: str) -> None:
        """Broadened keywords must not swallow unrelated queries.

        Note: "break" was added for coverage and also matches phrases such as
        "break down" / "take a break". That trade-off is accepted for the
        warranty domain, but genuinely unrelated queries must stay general_qa.
        """
        assert classify_intent(query) == IntentType.GENERAL_QA.value
