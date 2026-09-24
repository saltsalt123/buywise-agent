"""Eval-case integrity tests.

``eval_retrieval`` substring-matches each gold keyword against the retrieved chunk
text, so a gold entry that does not appear anywhere in the source data can never be
hit — it silently caps that case's recall below 1.0 with no failure anywhere.

case_002 read 0.8 for exactly that reason: its gold list used the query's
human-readable phrasing ("May 15") while the source files store ISO dates
("Date: 2026-05-15" in receipt.txt, and bank_statement.csv). The retriever was fine;
the gold list was wrong.

These tests assert the two properties that keep a case honest:
  1. every gold keyword exists somewhere in the corpus (otherwise it is unretrievable), and
  2. every gold keyword actually survives retrieval (otherwise recall < 1.0).
"""

from __future__ import annotations

import pytest

from agent.graph import _load_sample_data, run_workflow
from eval.run_all import EVAL_CASES


@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c.case_id)
def test_every_gold_keyword_exists_in_the_corpus(case) -> None:
    """A gold keyword absent from the data can never be retrieved — that is a gold bug."""
    chunks = _load_sample_data(case.input_sources)
    text = " ".join(c.text.lower() for c in chunks)
    absent = [kw for kw in case.gold_evidence_ids if kw.lower() not in text]
    assert not absent, (
        f"{case.case_id}: gold keyword(s) absent from the source data: {absent}. "
        "Fix the gold list to match the data's actual formatting, not the retriever."
    )


@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c.case_id)
def test_every_gold_keyword_survives_retrieval(case) -> None:
    """All gold keywords must reach the graph, i.e. evidence_recall should be 1.0."""
    result = run_workflow(case.user_query, case.input_sources)
    text = " ".join(c.text.lower() for c in result.get("retrieved_evidence", []))
    missing = [kw for kw in case.gold_evidence_ids if kw.lower() not in text]
    assert not missing, f"{case.case_id}: gold evidence indexed but never retrieved: {missing}"
