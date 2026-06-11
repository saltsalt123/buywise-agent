"""
BuyWise Agent MVP — CLI demo for warranty/return scenario.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def demo_warranty():
    """Run the headphone warranty claim demo."""
    from agent.graph import run_workflow

    print("=" * 60)
    print("  BuyWise Agent MVP — Warranty/Return Demo")
    print("=" * 60)
    print()

    case_dir = str(SAMPLE_DIR / "headphone_warranty_case")
    query = "My headphones stopped charging after 7 months. Can I claim warranty?"

    print(f"  📄 Source: headphone_warranty_case/")
    print(f"  💬 Query:  {query}")
    print()

    result = run_workflow(user_query=query, uploaded_source_ids=[case_dir])

    answer = result.get("final_answer", {}) or {}

    print("─" * 60)
    print("  📊 ANALYSIS RESULT")
    print("─" * 60)
    print(f"  Intent:        {result.get('intent', 'N/A')}")
    print(f"  Evidence used: {len(result.get('retrieved_evidence', []))} chunks")
    print(f"  Confidence:    {answer.get('overall_confidence', 'N/A')}")
    print()

    print("  📋 Key Facts:")
    for f in answer.get("key_facts", []):
        icon = "✅" if f.get("supported") else "⚠️"
        print(f"    {icon} [{f.get('confidence')}] {f.get('text', '')[:100]}")

    print()

    print("  ❓ Uncertainties:")
    unsupported = [u for u in answer.get("uncertainties", [])]
    if unsupported:
        for u in unsupported:
            print(f"    ⚠️  {u.get('text', '')[:80]}: {u.get('reason', '')}")
    else:
        print("    ✅ No unresolved uncertainties")

    print()

    print("  📝 Suggested Actions:")
    for a in answer.get("actions", []):
        badge = "🔓" if not a.get("requires_approval", True) else "🔒"
        print(f"    {badge} [{a.get('type', '')}] {a.get('description', '')}")
        if a.get("type") == "draft_email":
            body = a.get("payload", {}).get("body", "")
            print(f"       Draft: {body[:80]}...")

    print()
    print("=" * 60)
    print("  ✅ Demo complete — full workflow ran end-to-end")
    print("=" * 60)


def demo_laptop_return():
    """Run the laptop return scenario."""
    from agent.graph import run_workflow

    case_dir = str(SAMPLE_DIR / "laptop_return_case")
    query = "Can I return this laptop I bought on May 15?"

    result = run_workflow(user_query=query, uploaded_source_ids=[case_dir])
    answer = result.get("final_answer", {}) or {}

    print("─" * 60)
    print("  LAPTOP RETURN DEMO")
    print("─" * 60)
    print(f"  Intent: {result.get('intent')}")
    answer = result.get("final_answer", {}) or {}
    print(f"  Summary: {answer.get('summary', 'N/A')}")
    for f in answer.get("key_facts", []):
        print(f"    [{f.get('confidence')}] {f.get('text', '')[:100]}")
    for a in answer.get("actions", []):
        print(f"  → {a.get('description', '')}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "laptop":
        demo_laptop_return()
    else:
        demo_warranty()
