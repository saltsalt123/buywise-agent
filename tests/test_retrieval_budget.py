"""Retrieval-budget tests.

The retriever originally ran with ``top_k=10, max_chunks=5``, which starved the
graph: with 25 indexed chunks only ~8 reached the agents, and three gold keywords
(``receipt``, ``1 year``, ``purchase date``) were indexed but never retrieved.

The budget is now measured rather than guessed — recall saturates at
``top_k=20, max_chunks=15`` (case_001 1.00, case_002 0.80) and larger values give
no further gain. ``top_k`` is the binding constraint, so these tests assert on it
explicitly: raising ``max_chunks`` alone does nothing while ``top_k`` is small.
"""

from __future__ import annotations

from pathlib import Path

from agent.graph import _MAX_CHUNKS, _TOP_K, run_workflow

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"
HEADPHONE_CASE = str(SAMPLE_DATA / "headphone_warranty_case")

# Gold keywords for the headphone case. All five are reachable with the measured
# budget; the laptop case is deliberately excluded because one of its gold
# keywords ("May 15") does not appear in the data at all (it is stored as
# 2026-05-15), so it can never be retrieved regardless of budget.
HEADPHONE_GOLD = ["charging", "1 year", "purchase date", "warranty", "receipt"]


class TestBudgetIsNotReduced:
    def test_top_k_meets_measured_saturation_point(self) -> None:
        assert _TOP_K >= 20, (
            f"top_k={_TOP_K} is below the measured saturation point (20); "
            "recall drops as soon as the candidate pool shrinks"
        )

    def test_max_chunks_meets_measured_saturation_point(self) -> None:
        assert _MAX_CHUNKS >= 15, (
            f"max_chunks={_MAX_CHUNKS} is below the measured saturation point (15)"
        )


class TestGoldEvidenceReachesTheGraph:
    def test_all_gold_keywords_are_retrieved(self) -> None:
        """Every gold keyword must survive retrieval and reach the agent graph."""
        result = run_workflow(
            "My headphones stopped charging after 7 months. Can I claim warranty?",
            [HEADPHONE_CASE],
        )
        retrieved = result.get("retrieved_evidence", [])
        text = " ".join(c.text.lower() for c in retrieved)
        missing = [kw for kw in HEADPHONE_GOLD if kw.lower() not in text]
        assert not missing, (
            f"gold evidence indexed but never retrieved: {missing} "
            f"(budget top_k={_TOP_K}, max_chunks={_MAX_CHUNKS}; got {len(retrieved)} chunks)"
        )

    def test_every_source_type_is_represented(self) -> None:
        """The fallback must keep one chunk per doc_type even if keyword search misses it."""
        result = run_workflow(
            "My headphones stopped charging after 7 months. Can I claim warranty?",
            [HEADPHONE_CASE],
        )
        doc_types = {c.metadata.get("doc_type") for c in result.get("retrieved_evidence", [])}
        assert {"receipt", "email", "warranty"} <= doc_types, f"missing source types: {doc_types}"
