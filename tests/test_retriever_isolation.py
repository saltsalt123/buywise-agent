"""Each workflow run must index and search its own corpus.

``agent/graph.py`` kept the retriever in a module-level global::

    _RETRIEVER: SimpleRetriever | None = None

    def _get_retriever() -> SimpleRetriever:
        global _RETRIEVER
        if _RETRIEVER is None:
            _RETRIEVER = SimpleRetriever()
        return _RETRIEVER

``run_workflow`` set it to ``None`` at the start and every later node fetched it again by
name, so the corpus of a request lived in process-wide state.  Two requests in flight at
once both write ``index_chunks`` into the same object — the second overwrites the first —
and the doc-type fallback in ``retrieve_evidence_node`` reads ``retriever._chunks``, i.e.
whatever corpus was indexed last.  One user's receipts can be retrieved into another
user's answer.  That is a data-isolation defect, not just a stale cache.

The retriever therefore belongs to the run, not to the module.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import agent.graph as graph
from agent.graph import run_workflow

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data"

HEADPHONE_CASE = str(SAMPLE / "headphone_warranty_case")
LAPTOP_CASE = str(SAMPLE / "laptop_return_case")

HEADPHONE_QUERY = "My headphones stopped charging after 7 months. Can I claim warranty?"
LAPTOP_QUERY = "Can I return this laptop I bought on May 15?"

# Markers unique to each corpus.
HEADPHONE_MARKERS = ("SoundMax", "SM-PRO-X1", "SMPRX1")
LAPTOP_MARKERS = ("TECHWORLD", "PowerBook", "PB-15-M3")


def _evidence_text(result: dict) -> str:
    return " ".join(c.text for c in result.get("retrieved_evidence", []))


def _assert_isolated(label: str, text: str, foreign: tuple[str, ...]) -> None:
    leaked = [m for m in foreign if m in text]
    assert not leaked, f"{label}: evidence from the other request leaked in: {leaked}"


class TestSequentialRuns:
    def test_laptop_run_does_not_see_headphone_evidence(self) -> None:
        run_workflow(HEADPHONE_QUERY, [HEADPHONE_CASE])
        result = run_workflow(LAPTOP_QUERY, [LAPTOP_CASE])
        _assert_isolated("laptop after headphone", _evidence_text(result), HEADPHONE_MARKERS)

    def test_headphone_run_does_not_see_laptop_evidence(self) -> None:
        run_workflow(LAPTOP_QUERY, [LAPTOP_CASE])
        result = run_workflow(HEADPHONE_QUERY, [HEADPHONE_CASE])
        _assert_isolated("headphone after laptop", _evidence_text(result), LAPTOP_MARKERS)


class TestConcurrentRuns:
    """The case a process-wide retriever cannot survive.

    A thread barrier makes both runs enter the workflow at the same instant, so the window
    in which they can clobber each other's index is actually exercised.  The deterministic
    guard that the corpus is not held in a module global lives in
    ``TestNoProcessGlobalHoldsTheCorpus`` below.
    """

    ROUNDS = 8

    def test_interleaved_runs_keep_their_own_corpora(self) -> None:
        barrier = threading.Barrier(2)

        def drive(query: str, case: str) -> dict:
            barrier.wait(timeout=30)
            return run_workflow(query, [case])

        for round_index in range(self.ROUNDS):
            with ThreadPoolExecutor(max_workers=2) as pool:
                headphone = pool.submit(drive, HEADPHONE_QUERY, HEADPHONE_CASE)
                laptop = pool.submit(drive, LAPTOP_QUERY, LAPTOP_CASE)
                hp_result = headphone.result(timeout=30)
                lt_result = laptop.result(timeout=30)

            _assert_isolated(
                f"concurrent headphone run (round {round_index})",
                _evidence_text(hp_result),
                LAPTOP_MARKERS,
            )
            _assert_isolated(
                f"concurrent laptop run (round {round_index})",
                _evidence_text(lt_result),
                HEADPHONE_MARKERS,
            )

    def test_each_run_reports_only_its_own_doc_types(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            hp = pool.submit(run_workflow, HEADPHONE_QUERY, [HEADPHONE_CASE]).result(timeout=30)
            lt = pool.submit(run_workflow, LAPTOP_QUERY, [LAPTOP_CASE]).result(timeout=30)

        hp_types = {c.metadata.get("doc_type") for c in hp["retrieved_evidence"]}
        lt_types = {c.metadata.get("doc_type") for c in lt["retrieved_evidence"]}
        assert "policy" not in hp_types, (
            f"headphone run picked up the laptop's policy dir: {hp_types}"
        )
        assert "email" not in lt_types, f"laptop run picked up the headphone's email: {lt_types}"


class TestNoProcessGlobalHoldsTheCorpus:
    def test_module_does_not_retain_a_populated_retriever(self) -> None:
        """A global may exist, but it must not still hold a previous request's chunks."""
        run_workflow(HEADPHONE_QUERY, [HEADPHONE_CASE])
        holder = getattr(graph, "_RETRIEVER", None)
        leftover = list(getattr(holder, "_chunks", []) or [])
        assert not leftover, (
            f"the module-level retriever still holds {len(leftover)} chunk(s) from the last "
            "request; the corpus must be per-run, not process-wide"
        )

    def test_corpus_is_carried_on_the_state(self) -> None:
        """The run's own result must be self-contained: evidence lives in the returned state."""
        result = run_workflow(HEADPHONE_QUERY, [HEADPHONE_CASE])
        chunks = result.get("retrieved_evidence", [])
        assert chunks, "the run returned no evidence at all"
        source_ids = {c.source_id for c in chunks}
        assert source_ids == {c.source_id for c in chunks}
        holder = getattr(graph, "_RETRIEVER", None)
        assert not list(getattr(holder, "_chunks", []) or []), (
            "evidence should travel with the run's state, not with a module global"
        )
