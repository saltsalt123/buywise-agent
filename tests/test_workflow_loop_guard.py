"""Loop-guard tests for the re-retrieval branch.

``route_after_verify`` sends the graph back to ``retrieve_evidence`` whenever
``unsupported_claims`` is non-empty and ``retrieval_attempts < 2``.  Only
``ingest_and_index_node`` ever incremented that counter, and it runs exactly once,
so on the second pass the counter was still ``1``, the branch was taken again, and
the graph re-entered ``retrieve -> specialists -> verify`` forever.  The workflow
never returned.

Trigger: a receipt that yields a purchase-date claim at confidence 0.6.  The order
agent lowers that claim's confidence when no merchant name is recognised
(``order_agent.py``: ``0.85 if facts.merchant else 0.6``), and the claim's own terms
are not all present in the evidence text, so the verifier files it under
``unsupported_claims`` and the loop starts.

The workflow is driven in a child process with a hard timeout, so a regression is
reported as a clean assertion failure instead of hanging the whole test session.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# A receipt with a purchase date but no recognisable merchant and no "purchase"
# wording of its own.  This is the shape that produces the unsupported
# purchase-date claim described above.
LOOPING_RECEIPT = """Store #12
2026-05-15
Total 1299.00
"""

# A receipt that also carries the words the verifier needs to support the supervisor's
# intent claim ("warranty", "return").  Nothing ends up unsupported, so no re-retrieval
# branch is taken and the counter stays at 1.
SUPPORTED_RECEIPT = """Amazon
2026-05-15
Return Policy: 30 days from purchase date
Warranty: 1 year manufacturer warranty included
Total 1299.00
"""

_QUERY = "I want a refund for my laptop"

_CHILD = r'''
import json, os, sys
sys.path.insert(0, {root!r})
os.chdir({root!r})
from agent.graph import run_workflow

result = run_workflow({query!r}, [{src!r}])
answer = result.get("final_answer") or {{}}
print("__RESULT__" + json.dumps({{
    "retrieval_attempts": result.get("retrieval_attempts"),
    "unsupported": len(result.get("unsupported_claims") or []),
    "verified": len(result.get("verified_claims") or []),
    "agent_messages": len(result.get("agent_messages") or []),
    "status": answer.get("status"),
    "has_answer": bool(answer),
}}))
'''


def _case_dir(receipt_text: str, filename: str, tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / filename).write_text(receipt_text)
    return case_dir


def _drive(case_dir: Path, timeout: float = 3.0) -> tuple[bool, dict | None]:
    """Run the workflow in a child process; return (finished_within_timeout, payload)."""
    script = _CHILD.format(root=str(ROOT), query=_QUERY, src=str(case_dir))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return False, None

    for line in proc.stdout.splitlines():
        if line.startswith("__RESULT__"):
            return True, json.loads(line[len("__RESULT__"):])
    pytest.fail(f"child produced no result; rc={proc.returncode}\n{proc.stderr[-2000:]}")
    return False, None  # unreachable; keeps type checkers happy


def _payload(case_dir: Path) -> dict:
    """Drive the workflow and require that it actually returned."""
    finished, payload = _drive(case_dir)
    assert finished, (
        "run_workflow did not return within 3s — the unsupported-claim re-retrieval "
        "branch is looping"
    )
    assert payload is not None
    return payload


class TestWorkflowTerminates:
    """The graph must always come back, however weak the evidence."""

    def test_returns_within_three_seconds(self, tmp_path: Path) -> None:
        finished, _ = _drive(_case_dir(LOOPING_RECEIPT, "receipt.txt", tmp_path), timeout=3.0)
        assert finished, (
            "run_workflow did not return within 3s — the unsupported-claim re-retrieval "
            "branch is looping"
        )

    def test_retrieval_attempts_advances_instead_of_sticking_at_one(self, tmp_path: Path) -> None:
        payload = _payload(_case_dir(LOOPING_RECEIPT, "receipt.txt", tmp_path))
        assert payload["retrieval_attempts"] > 1, (
            "retrieval_attempts stayed at 1, so the loop guard can never fire; the "
            "counter has to advance on the retrieve branch, not only at ingest"
        )

    def test_retrieval_attempts_stays_bounded(self, tmp_path: Path) -> None:
        payload = _payload(_case_dir(LOOPING_RECEIPT, "receipt.txt", tmp_path))
        assert payload["retrieval_attempts"] <= 3, (
            f"retrieval_attempts={payload['retrieval_attempts']} — the budget is meant to "
            "stop re-retrieval at one extra pass"
        )

    def test_agent_messages_do_not_grow_without_bound(self, tmp_path: Path) -> None:
        payload = _payload(_case_dir(LOOPING_RECEIPT, "receipt.txt", tmp_path))
        # supervisor + order + policy + verifier (+ one more verifier pass) + action
        assert payload["agent_messages"] <= 10, (
            f"agent_messages={payload['agent_messages']} — the message list grows on every "
            "pass through the loop"
        )


class TestUnsupportedClaimsStillProduceAnAnswer:
    """Running out of retrieval budget is not an error: the user still gets an answer."""

    def test_final_response_is_returned(self, tmp_path: Path) -> None:
        payload = _payload(_case_dir(LOOPING_RECEIPT, "receipt.txt", tmp_path))
        assert payload["has_answer"], "workflow must still produce a final_answer"
        assert payload["status"], "final_answer must carry a status"

    def test_supported_receipt_does_not_enter_the_loop(self, tmp_path: Path) -> None:
        """Control: when every claim is supported, no re-retrieval happens."""
        payload = _payload(_case_dir(SUPPORTED_RECEIPT, "receipt.txt", tmp_path))
        assert payload["unsupported"] == 0
        assert payload["retrieval_attempts"] == 1
