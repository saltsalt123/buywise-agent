"""
BuyWise Agent MVP — Eval runner (warranty/return focus).
"""
from __future__ import annotations

import time
from pathlib import Path

from agent.graph import run_workflow
from agent.state import EvalCase

SAMPLE = str(Path(__file__).resolve().parent.parent / "sample_data")

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
        gold_evidence_ids=["return policy", "14 days", "May 15", "laptop", "receipt"],
        forbidden_claims=["You can return for a full refund with no restrictions"],
        expected_actions=["draft_email"],
    ),
]


# ── Metrics ─────────────────────────────────────────────────────────────────

def eval_retrieval(case: EvalCase, result: dict) -> dict:
    """Check gold-evidence keywords appear in retrieved chunks."""
    chunk_texts = " ".join(c.text.lower() for c in result.get("retrieved_evidence", []))
    hits = sum(1 for keyword in case.gold_evidence_ids if keyword.lower() in chunk_texts)
    recall = hits / max(len(case.gold_evidence_ids), 1)
    return {"metric": "evidence_recall", "score": round(recall, 3), "hits": hits, "total": len(case.gold_evidence_ids)}


def eval_forbidden(case: EvalCase, result: dict) -> dict:
    """Check forbidden claims are NOT in the output."""
    answer = result.get("final_answer", {}) or {}
    all_text = " ".join(
        [answer.get("summary", "")]
        + [f.get("text", "") for f in answer.get("key_facts", [])]
    ).lower()
    violations = [c for c in case.forbidden_claims if c.lower() in all_text]
    score = 1.0 - (len(violations) / max(len(case.forbidden_claims), 1))
    return {"metric": "forbidden_claim_avoidance", "score": round(score, 3), "violations": violations}


def eval_actions(case: EvalCase, result: dict) -> dict:
    """Check expected action types appear."""
    actions = result.get("final_answer", {}).get("actions", [])
    types = [a.get("type", "") for a in actions]
    hits = sum(1 for e in case.expected_actions if e in types)
    return {"metric": "action_generation", "score": round(hits / max(len(case.expected_actions), 1), 3), "hits": hits, "total": len(case.expected_actions)}


def eval_confidence(result: dict) -> dict:
    """Ensure confidence is reported."""
    c = (result.get("final_answer") or {}).get("overall_confidence", 0)
    return {"metric": "confidence_reported", "score": 1.0 if c and c > 0 else 0.0}


# ── Runner ──────────────────────────────────────────────────────────────────

def run_all(output_path: str | None = None):
    results = []
    for case in EVAL_CASES:
        print(f"\n{'='*55}")
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
            print(f"  ⏱  {elapsed:.2f}s ✅")

            for m in metrics:
                status = "✅" if m["score"] >= 0.5 else "⚠️"
                print(f"    {status} {m['metric']}: {m['score']}")

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ❌ FAILED ({elapsed:.1f}s): {e}")
            results.append({"case_id": case.case_id, "status": "failed", "elapsed_s": round(elapsed, 1), "error": str(e), "metrics": []})

    report = _format_report(results)
    print(f"\n{'='*55}")
    print("  EVAL SUMMARY")
    print(f"{'='*55}")
    for r in results:
        emoji = "✅" if r["status"] == "passed" else "❌"
        print(f"  {emoji} {r['case_id']} ({r['elapsed_s']}s)")
        for m in r.get("metrics", []):
            print(f"      {m['metric']}: {m['score']}")

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(report)
        print(f"\n  📄 Report → {output_path}")


def _format_report(results: list) -> str:
    lines = ["# BuyWise Agent MVP — Eval Report", f"\n**Cases:** {len(results)}"]
    for r in results:
        lines.append(f"\n## {'✅' if r['status']=='passed' else '❌'} {r['case_id']}")
        lines.append(f"- Status: {r['status']} ({r['elapsed_s']}s)")
        lines.append(f"- Summary: {r.get('summary', 'N/A')}")
        if r.get("error"):
            lines.append(f"- Error: {r['error']}")
        for m in r.get("metrics", []):
            lines.append(f"- {m['metric']}: **{m['score']}**")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="eval/reports/latest.md")
    args = parser.parse_args()
    run_all(args.output)
