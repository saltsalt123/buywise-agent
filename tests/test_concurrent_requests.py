"""Concurrency stress: two requests in flight must not share a corpus.

The retriever was a module-level ``_RETRIEVER`` singleton, so two runs overlapped on one
object: the second ``index_chunks`` overwrote the first, and the doc-type fallback in
``retrieve_evidence_node`` reads ``retriever._chunks``.  That is a data-isolation defect —
one user's receipts can be retrieved into another user's answer.

A thread barrier is used so both runs enter the workflow at the same instant and the
interleaving window is actually exercised.  ``tests/test_retriever_isolation.py`` holds the
smaller deterministic guard; this file is the volume test.
"""

from __future__ import annotations

import threading
import time
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

# Markers that appear only in one corpus.
HEADPHONE_MARKERS = ("SoundMax", "SM-PRO-X1", "SMPRX1")
LAPTOP_MARKERS = ("TECHWORLD", "PowerBook", "PB-15-M3")

ROUNDS = 24
MAX_ROUND_SECONDS = 30.0


def _text(result: dict) -> str:
    return " ".join(c.text for c in result.get("retrieved_evidence", []))


def _leaks(text: str, foreign: tuple[str, ...]) -> list[str]:
    return [m for m in foreign if m in text]


class TestConcurrentWorkflowRuns:
    def test_twenty_four_interleaved_rounds_stay_isolated(self) -> None:
        barrier = threading.Barrier(2)

        def drive(query: str, case: str) -> dict:
            barrier.wait(timeout=MAX_ROUND_SECONDS)
            return run_workflow(query, [case])

        started = time.monotonic()
        for round_index in range(ROUNDS):
            with ThreadPoolExecutor(max_workers=2) as pool:
                hp = pool.submit(drive, HEADPHONE_QUERY, HEADPHONE_CASE)
                lt = pool.submit(drive, LAPTOP_QUERY, LAPTOP_CASE)
                hp_result = hp.result(timeout=MAX_ROUND_SECONDS)
                lt_result = lt.result(timeout=MAX_ROUND_SECONDS)

            hp_leaks = _leaks(_text(hp_result), LAPTOP_MARKERS)
            lt_leaks = _leaks(_text(lt_result), HEADPHONE_MARKERS)
            assert not hp_leaks, f"round {round_index}: headphone run saw {hp_leaks}"
            assert not lt_leaks, f"round {round_index}: laptop run saw {lt_leaks}"

        elapsed = time.monotonic() - started
        assert elapsed < MAX_ROUND_SECONDS, (
            f"{ROUNDS} rounds took {elapsed:.1f}s, which suggests contention rather than "
            "parallel work"
        )

    def test_answers_are_not_shared_between_threads(self) -> None:
        """Even the final answers must differ; identical ones would mean one run won."""
        barrier = threading.Barrier(2)

        def drive(query: str, case: str) -> dict:
            barrier.wait(timeout=MAX_ROUND_SECONDS)
            return run_workflow(query, [case])

        with ThreadPoolExecutor(max_workers=2) as pool:
            hp_future = pool.submit(drive, HEADPHONE_QUERY, HEADPHONE_CASE)
            lt_future = pool.submit(drive, LAPTOP_QUERY, LAPTOP_CASE)
            hp = hp_future.result(timeout=MAX_ROUND_SECONDS)
            lt = lt_future.result(timeout=MAX_ROUND_SECONDS)

        assert (hp.get("final_answer") or {}).get("summary") != (
            lt.get("final_answer") or {}
        ).get("summary")

        hp_types = {c.metadata.get("doc_type") for c in hp["retrieved_evidence"]}
        lt_types = {c.metadata.get("doc_type") for c in lt["retrieved_evidence"]}
        assert "policy" not in hp_types, f"headphone run picked up laptop documents: {hp_types}"
        assert "email" not in lt_types, f"laptop run picked up headphone documents: {lt_types}"


class TestNoProcessGlobalCorpus:
    def test_module_global_holds_no_chunks_after_a_run(self) -> None:
        run_workflow(HEADPHONE_QUERY, [HEADPHONE_CASE])
        holder = getattr(graph, "_RETRIEVER", None)
        leftover = list(getattr(holder, "_chunks", []) or [])
        assert not leftover, (
            f"the module-level retriever still holds {len(leftover)} chunk(s) from the last "
            "request; the corpus must be per-run"
        )

    def test_module_global_holds_no_chunks_after_concurrent_runs(self) -> None:
        barrier = threading.Barrier(2)

        def drive(query: str, case: str) -> dict:
            barrier.wait(timeout=MAX_ROUND_SECONDS)
            return run_workflow(query, [case])

        with ThreadPoolExecutor(max_workers=2) as pool:
            hp_future = pool.submit(drive, HEADPHONE_QUERY, HEADPHONE_CASE)
            lt_future = pool.submit(drive, LAPTOP_QUERY, LAPTOP_CASE)
            hp_future.result(timeout=MAX_ROUND_SECONDS)
            lt_future.result(timeout=MAX_ROUND_SECONDS)

        holder = getattr(graph, "_RETRIEVER", None)
        assert not list(getattr(holder, "_chunks", []) or [])


class TestConcurrentApiRequests:
    """The endpoint path, where a shared transport or client could also leak state."""

    API_ROUNDS = 4

    def test_api_requests_in_parallel_stay_isolated(self) -> None:
        from fastapi.testclient import TestClient

        import apps.api.main as api

        barrier = threading.Barrier(2)

        def drive(query: str, source_dir: str) -> dict:
            client = TestClient(api.app)
            barrier.wait(timeout=MAX_ROUND_SECONDS)
            response = client.post("/api/chat", json={"query": query, "source_dirs": [source_dir]})
            assert response.status_code == 200, response.text
            return response.json()

        for round_index in range(self.API_ROUNDS):
            with ThreadPoolExecutor(max_workers=2) as pool:
                hp = pool.submit(drive, HEADPHONE_QUERY, "sample_data/headphone_warranty_case")
                lt = pool.submit(drive, LAPTOP_QUERY, "sample_data/laptop_return_case")
                hp_body = hp.result(timeout=MAX_ROUND_SECONDS)
                lt_body = lt.result(timeout=MAX_ROUND_SECONDS)

            hp_text = " ".join(f.get("text", "") for f in hp_body["key_facts"])
            lt_text = " ".join(f.get("text", "") for f in lt_body["key_facts"])
            hp_leaks = _leaks(hp_text, LAPTOP_MARKERS)
            lt_leaks = _leaks(lt_text, HEADPHONE_MARKERS)
            assert not hp_leaks, f"round {round_index}: headphone answer carried {hp_leaks}"
            assert not lt_leaks, f"round {round_index}: laptop answer carried {lt_leaks}"

            # The two answers must be about different products, not the same one twice.
            assert hp_body["status"] == "complete"
            assert lt_body["status"] == "complete"
            assert hp_body["summary"] != lt_body["summary"], (
                f"round {round_index}: both concurrent requests returned the same answer"
            )
