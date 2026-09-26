"""
BuyWise Agent MVP — Eval runner (warranty/return focus).

Two suites:

* **positive cases** — the two sample scenarios, scored on evidence recall, forbidden-claim
  avoidance, action generation and confidence reporting.
* **negative cases** — runs where the correct behaviour is to *refuse*: no documents, nothing
  parsable, an unimplemented intent, and the re-retrieval loop guard.  These are reported
  separately because an eval that only prints "8/8" says nothing about whether the system
  knows when to stop.  A negative case passes when the system declines to answer as if it
  had evidence.
"""
from __future__ import annotations

import shutil
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from agent.graph import run_workflow
from agent.state import EvalCase

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = str(ROOT / "sample_data")

# ── Two core eval cases ─────────────────────────────────────────────────────

EVAL_CASES = [
    EvalCase(
        case_id="case_001_headphone_warranty",
        user_query="My headphones stopped charging after 7 months. Can I claim warranty?",
        input_sources=[f"{SAMPLE}/headphone_warranty_case"],
        expected_decision="warranty_likely_valid",
        gold_evidence_ids=["charging", "1 year", "purchase date", "warranty", "receipt"],
        forbidden_claims=[
            "The user is guaranteed a free replacement",
            "The store must refund the product",
        ],
        expected_actions=["draft_email"],
    ),
    EvalCase(
        case_id="case_002_laptop_return",
        user_query="Can I return this laptop I bought on May 15?",
        input_sources=[f"{SAMPLE}/laptop_return_case"],
        expected_decision="return_window_analysis",
        # "May 15" is the human-readable form used in the query, but the source files
        # store ISO dates ("Date: 2026-05-15" in receipt.txt, and bank_statement.csv).
        # Gold keywords are substring-matched against chunk text, so a gold entry that
        # matches the query's phrasing instead of the data's silently caps recall below
        # 1.0 — this case read 0.8 for exactly that reason.
        gold_evidence_ids=["return policy", "14 days", "2026-05-15", "laptop", "receipt"],
        forbidden_claims=["You can return for a full refund with no restrictions"],
        expected_actions=["draft_email"],
    ),
]


# ── Negative cases ─────────────────────────────────────────────────────────
#
# Each entry states what the system must NOT do.  `kind` decides which documents (if any)
# are supplied; the checks are applied to the finished run.

NEGATIVE_CASES = [
    {
        "case_id": "neg_001_no_documents_at_all",
        "kind": "empty_dir",
        "user_query": "Can I return this laptop I bought on May 15?",
        "expect_status": {"no_evidence", "insufficient_evidence"},
        "forbid_actions": {"act_return_request", "act_warranty_claim"},
        "max_confidence": 0.0,
    },
    {
        "case_id": "neg_002_nothing_parsable",
        "kind": "unparsable_dir",
        "user_query": "Can I return this laptop I bought on May 15?",
        "expect_status": {"no_evidence", "insufficient_evidence"},
        "forbid_actions": {"act_return_request", "act_warranty_claim"},
        "max_confidence": 0.0,
    },
    {
        "case_id": "neg_003_unimplemented_intent",
        "kind": "existing_dir",
        "source": f"{SAMPLE}/laptop_return_case",
        "user_query": "Which laptop should I buy?",
        "expect_status": {"unsupported_intent"},
        "forbid_actions": None,
        "expect_no_actions": True,       # the whole action list must be empty
        "max_confidence": 0.0,
        "expect_no_key_facts": True,
    },
    {
        "case_id": "neg_004_loop_guard_terminates",
        "kind": "receipt_only_dir",
        "user_query": "I want a refund for my laptop",
        "expect_status": None,
        "forbid_actions": None,
        "max_confidence": None,
        "max_retrieval_attempts": 2,
        "max_elapsed_s": 5.0,
    },
    {
        # Receipt grants a 30-day window; the merchant's own policy and support email refuse
        # returns outright. The workflow must not pick a side.
        "case_id": "case_contradictory_policy",
        "kind": "contradictory_dir",
        "user_query": "Can I return this laptop I bought last week?",
        "expect_status": {"needs_human_review"},
        "forbid_actions": {"act_return_request"},
        "expect_actions": {"act_return_exception_request"},
        "max_confidence": 0.5,
        "expect_conflict_claim": True,
        "expect_summary_mentions": (
            "conflict",
            "final sale",
            "no returns",
            "disagree",
            "contradict",
        ),
    },
]

FILLER_RECEIPT = "Store #12\n2026-05-15\nTotal 1299.00\n"

# The contradictory fixture is built here rather than imported from `tests/` so the shipped
# eval does not depend on the test tree. It mirrors tests/case_fixtures.contradictory_case.
CONTRADICTORY_POLICY_HTML = """<html><body>
<div class="return-policy">
<h1>TechWorld Clearance Terms</h1>
<p><strong>Return Window:</strong> Final sale - no returns accepted on clearance items</p>
<p><strong>Condition:</strong> All sales final. Items are sold as-is.</p>
<p><strong>Refund:</strong> No refunds or exchanges are available for this order.</p>
</div></body></html>
"""

CONTRADICTORY_EMAIL = """From: support@techworld.example
To: customer@email.example
Subject: Re: Return request for order ORD-20260515-3342
Date: Mon, 01 Jun 2026 10:05:33 +0800

Hello,

This order was placed during our clearance event and the item is final sale, so we are not
able to accept a return for it. No refunds or exchanges apply to clearance purchases.

Best regards,
TechWorld Support
"""


def _contradictory_documents(target: Path, days_ago: int = 5, window_days: int = 30) -> str:
    """A receipt with an *open* window plus documents that refuse returns.

    The purchase date is placed relative to today so the window is still open: the conflict,
    not expiry, has to be what the run reacts to.
    """
    target.mkdir(parents=True, exist_ok=True)
    purchase = (date.today() - timedelta(days=days_ago)).isoformat()
    (target / "receipt.txt").write_text(
        "TECHWORLD INC. - SALES RECEIPT\n"
        "----------------------------------------\n"
        f"Date: {purchase} 16:20:00\n"
        'Item: PowerBook Pro 15"\n'
        "Total: $1,299.00\n\n"
        f"Return Policy: {window_days} days from purchase date\n"
    )
    (target / "return_policy.html").write_text(CONTRADICTORY_POLICY_HTML)
    (target / "support_email.eml").write_text(CONTRADICTORY_EMAIL)
    return str(target)


def _make_source(kind: str, spec: dict) -> tuple[str, str | None]:
    """Create the documents for a negative case; return (path, cleanup_dir)."""
    if kind == "existing_dir":
        return spec["source"], None

    tmp = tempfile.mkdtemp(prefix="buywise_neg_")
    if kind == "empty_dir":
        return tmp, tmp
    if kind == "unparsable_dir":
        Path(tmp, "scan.bin").write_bytes(b"\x00\x01\x02 not a supported document")
        Path(tmp, "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return tmp, tmp
    if kind == "receipt_only_dir":
        Path(tmp, "receipt.txt").write_text(FILLER_RECEIPT)
        return tmp, tmp
    if kind == "contradictory_dir":
        return _contradictory_documents(Path(tmp)), tmp
    raise ValueError(f"unknown negative-case kind: {kind}")


def eval_negative_case(case: dict) -> dict:
    """Run one negative case and report every check it makes."""
    source, cleanup = _make_source(case["kind"], case)
    started = time.time()
    checks: list[dict] = []
    try:
        result = run_workflow(case["user_query"], [source])
        elapsed = time.time() - started
        answer = result.get("final_answer") or {}

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "ok": bool(ok), "detail": detail})

        if case.get("expect_status"):
            status = answer.get("status")
            check(
                "status",
                status in case["expect_status"],
                f"status={status!r} expected one of {sorted(case['expect_status'])}",
            )

        if case.get("forbid_actions"):
            ids = {a.get("action_id") for a in answer.get("actions", [])}
            forbidden = ids & case["forbid_actions"]
            check(
                "no_documents_drafted",
                not forbidden,
                f"drafted {sorted(forbidden)}" if forbidden else "no forbidden actions",
            )

        if case.get("expect_no_actions"):
            ids = {a.get("action_id") for a in answer.get("actions", [])}
            check("no_actions", not ids, f"actions={sorted(ids)}")

        if case.get("max_confidence") is not None:
            confidence = answer.get("overall_confidence")
            check(
                "confidence_not_overstated",
                (confidence or 0.0) <= case["max_confidence"],
                f"overall_confidence={confidence}",
            )

        if case.get("expect_no_key_facts"):
            facts = answer.get("key_facts") or []
            check("no_key_facts", not facts, f"key_facts={len(facts)}")

        if case.get("expect_actions"):
            ids = {a.get("action_id") for a in answer.get("actions", [])}
            missing = case["expect_actions"] - ids
            check(
                "expected_actions_present",
                not missing,
                f"missing {sorted(missing)}" if missing else f"present: {sorted(ids)}",
            )

        if case.get("expect_conflict_claim"):
            ids = {c.claim_id for c in result.get("verified_claims", [])}
            recorded = "policy_return_conflict" in ids
            check(
                "conflict_recorded",
                recorded,
                f"policy_return_conflict {'present' if recorded else 'absent'}",
            )

        if case.get("expect_summary_mentions"):
            summary = str(answer.get("summary", "")).lower()
            hit = [w for w in case["expect_summary_mentions"] if w in summary]
            detail = f"matched {hit}" if hit else f"none of {case['expect_summary_mentions']}"
            check("summary_explains_the_conflict", bool(hit), detail)

        if case.get("max_retrieval_attempts") is not None:
            attempts = result.get("retrieval_attempts")
            check(
                "retrieval_budget_bounded",
                attempts is not None and attempts <= case["max_retrieval_attempts"],
                f"retrieval_attempts={attempts}",
            )

        if case.get("max_elapsed_s") is not None:
            check(
                "terminates_in_time",
                elapsed <= case["max_elapsed_s"],
                f"elapsed={elapsed:.2f}s limit={case['max_elapsed_s']}s",
            )

        return {
            "case_id": case["case_id"],
            "status": "passed" if all(c["ok"] for c in checks) else "failed",
            "elapsed_s": round(elapsed, 2),
            "checks": checks,
            "summary": answer.get("summary", ""),
            "final_status": answer.get("status"),
        }
    except Exception as exc:  # a hang or crash is itself a failure
        return {
            "case_id": case["case_id"],
            "status": "failed",
            "elapsed_s": round(time.time() - started, 2),
            "checks": checks,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


# ── Metrics ─────────────────────────────────────────────────────────────────

def eval_retrieval(case: EvalCase, result: dict) -> dict:
    """Check gold-evidence keywords appear in retrieved chunks."""
    chunk_texts = " ".join(c.text.lower() for c in result.get("retrieved_evidence", []))
    hits = sum(1 for keyword in case.gold_evidence_ids if keyword.lower() in chunk_texts)
    recall = hits / max(len(case.gold_evidence_ids), 1)
    return {
        "metric": "evidence_recall",
        "score": round(recall, 3),
        "hits": hits,
        "total": len(case.gold_evidence_ids),
    }


def eval_forbidden(case: EvalCase, result: dict) -> dict:
    """Check forbidden claims are NOT in the output."""
    answer = result.get("final_answer", {}) or {}
    all_text = " ".join(
        [answer.get("summary", "")]
        + [f.get("text", "") for f in answer.get("key_facts", [])]
    ).lower()
    violations = [c for c in case.forbidden_claims if c.lower() in all_text]
    score = 1.0 - (len(violations) / max(len(case.forbidden_claims), 1))
    return {
        "metric": "forbidden_claim_avoidance",
        "score": round(score, 3),
        "violations": violations,
    }


def eval_actions(case: EvalCase, result: dict) -> dict:
    """Check expected action types appear."""
    actions = result.get("final_answer", {}).get("actions", [])
    types = [a.get("type", "") for a in actions]
    hits = sum(1 for e in case.expected_actions if e in types)
    return {
        "metric": "action_generation",
        "score": round(hits / max(len(case.expected_actions), 1), 3),
        "hits": hits,
        "total": len(case.expected_actions),
    }


def eval_confidence(result: dict) -> dict:
    """Ensure confidence is reported."""
    c = (result.get("final_answer") or {}).get("overall_confidence", 0)
    return {"metric": "confidence_reported", "score": 1.0 if c and c > 0 else 0.0}


# ── Runner ──────────────────────────────────────────────────────────────────

def run_positive_cases() -> list[dict]:
    results = []
    for case in EVAL_CASES:
        print(f"\n{'-' * 55}")
        print(f"  Case: {case.case_id}")
        print(f"  Query: {case.user_query[:60]}...")
        start = time.time()

        try:
            result = run_workflow(
                user_query=case.user_query,
                uploaded_source_ids=case.input_sources,
            )
            elapsed = time.time() - start

            metrics = [
                eval_retrieval(case, result),
                eval_forbidden(case, result),
                eval_actions(case, result),
                eval_confidence(result),
            ]
            results.append({
                "case_id": case.case_id,
                "status": "passed",
                "elapsed_s": round(elapsed, 2),
                "metrics": metrics,
                "summary": (result.get("final_answer") or {}).get("summary", ""),
            })
            print(f"  {elapsed:.2f}s OK")

            for m in metrics:
                mark = "OK " if m["score"] >= 0.5 else "!! "
                print(f"    {mark} {m['metric']}: {m['score']}")

        except Exception as e:
            elapsed = time.time() - start
            print(f"  FAILED ({elapsed:.1f}s): {e}")
            results.append({
                "case_id": case.case_id,
                "status": "failed",
                "elapsed_s": round(elapsed, 1),
                "error": str(e),
                "metrics": [],
            })
    return results


def run_all(output_path: str | None = None):
    positive = run_positive_cases()

    print(f"\n{'=' * 55}")
    print("  NEGATIVE CASES (the system must refuse to overclaim)")
    print(f"{'=' * 55}")
    negatives = []
    for case in NEGATIVE_CASES:
        outcome = eval_negative_case(case)
        negatives.append(outcome)
        mark = "OK " if outcome["status"] == "passed" else "!! "
        print(f"  {mark} {outcome['case_id']} ({outcome['elapsed_s']}s)")
        for c in outcome.get("checks", []):
            print(f"        {'PASS' if c['ok'] else 'FAIL'}  {c['check']}: {c['detail']}")
        if outcome.get("error"):
            print(f"        ERROR: {outcome['error']}")

    report = _format_report(positive, negatives)
    print(f"\n{'=' * 55}")
    print("  EVAL SUMMARY")
    print(f"{'=' * 55}")
    for r in positive:
        emoji = "OK " if r["status"] == "passed" else "XX "
        print(f"  {emoji}{r['case_id']} ({r['elapsed_s']}s)")
        for m in r.get("metrics", []):
            print(f"      {m['metric']}: {m['score']}")
    passed_positive = sum(1 for r in positive if r["status"] == "passed")
    passed_negative = sum(1 for r in negatives if r["status"] == "passed")
    print(f"  positive: {passed_positive}/{len(positive)} cases")
    print(f"  negative: {passed_negative}/{len(negatives)} cases")

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(report)
        print(f"\n  Report -> {output_path}")

    return positive, negatives


def _format_report(results: list, negatives: list) -> str:
    lines = [
        "# BuyWise Agent MVP — Eval Report",
        f"\n**Positive cases:** {len(results)}",
        f"**Negative cases:** {len(negatives)}",
    ]

    lines.append("\n## Positive cases\n")
    for r in results:
        lines.append(f"### {'PASS' if r['status'] == 'passed' else 'FAIL'} {r['case_id']}")
        lines.append(f"- Status: {r['status']} ({r['elapsed_s']}s)")
        lines.append(f"- Summary: {r.get('summary', 'N/A')}")
        if r.get("error"):
            lines.append(f"- Error: {r['error']}")
        for m in r.get("metrics", []):
            lines.append(f"- {m['metric']}: **{m['score']}**")
        lines.append("")

    lines.append("## Negative cases (the system must refuse to overclaim)\n")
    lines.append(
        "A negative case passes when the run declines to answer as if it had evidence: "
        "correct status, no drafted documents, no overstated confidence, and a bounded "
        "retrieval budget.\n"
    )
    for n in negatives:
        lines.append(f"### {'PASS' if n['status'] == 'passed' else 'FAIL'} {n['case_id']}")
        lines.append(f"- Status: {n['status']} ({n['elapsed_s']}s)")
        if n.get("final_status"):
            lines.append(f"- Reported status: {n['final_status']}")
        if n.get("error"):
            lines.append(f"- Error: {n['error']}")
        for c in n.get("checks", []):
            lines.append(f"- {'✅' if c['ok'] else '❌'} {c['check']}: {c['detail']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="eval/reports/latest.md")
    args = parser.parse_args()
    run_all(args.output)
