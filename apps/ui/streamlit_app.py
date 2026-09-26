"""BuyWise Agent — Streamlit UI (phase 7, minimal).

Lets a user drop in a receipt / warranty card / policy / email, ask a question, and read the
same analysis the CLI demo prints. Everything runs in-process against the local workflow —
no external services, no accounts, no network calls.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import streamlit as st

from apps.safe_paths import UPLOAD_ROOT
from apps.ui.uploads import (
    ALLOWED_UPLOAD_EXTENSIONS,
    SAMPLE_CASES,
    UnsafeUploadError,
    analyze,
    clear_session_dir,
    new_session_dir,
    sample_case_path,
    save_uploads,
)

DEFAULT_QUERY = "My headphones stopped charging after 7 months. Can I claim warranty?"

# Each sample case gets the question it was written for, so the shortcut is one click.
SAMPLE_QUERIES = {
    "headphone": DEFAULT_QUERY,
    "laptop": "Can I return this laptop I bought on May 15?",
}

STATUS_LABELS = {
    "complete": "✅ complete",
    "needs_human_review": "⚠️ needs human review",
    "no_evidence": "🚫 no evidence",
    "insufficient_evidence": "🚫 insufficient evidence",
    "unsupported_intent": "❔ unsupported intent",
}


def _session_dir() -> Path:
    """One upload directory per browser session, stable across Streamlit's re-runs."""
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = uuid4().hex
    return new_session_dir(st.session_state["session_id"])


def _sidebar() -> tuple[list, str | None]:
    """Uploads and the sample shortcuts. Returns (uploaded files, loaded sample name)."""
    with st.sidebar:
        st.header("Documents")

        uploaded = st.file_uploader(
            "Receipt, warranty, policy, email",
            type=sorted(ext.lstrip(".") for ext in ALLOWED_UPLOAD_EXTENSIONS),
            accept_multiple_files=True,
            help="Files stay in a local session directory; nothing is uploaded anywhere.",
        )

        st.subheader("Or load a sample case")
        loaded: str | None = None
        for name in sorted(SAMPLE_CASES):
            label = name.replace("_", " ").capitalize()
            if st.button(f"Load {label} sample", use_container_width=True):
                loaded = name

        if st.session_state.get("source_dir"):
            st.caption(f"Session dir: `{st.session_state['source_dir']}`")
            st.caption(f"Uploads live under `{UPLOAD_ROOT.name}/` (git-ignored).")
        return uploaded, loaded


def _run(query: str, uploaded: list, loaded_sample: str | None) -> None:
    """Resolve the document set, run the workflow, and keep the result for rendering.

    A sample button is an explicit choice about *this* run, so it wins over files that happen
    to still be staged in the uploader; otherwise the uploads are the more recent input.
    """
    try:
        if loaded_sample:
            source_dir = sample_case_path(loaded_sample)
            origin = f"sample case: {loaded_sample}"
        elif uploaded:
            session = _session_dir()
            save_uploads(session, [(f.name, f.getvalue()) for f in uploaded])
            source_dir = session
            origin = f"{len(uploaded)} uploaded file(s)"
        elif st.session_state.get("source_dir"):
            source_dir = Path(st.session_state["source_dir"])
            origin = "previous documents"
        else:
            st.warning("Upload at least one document, or load a sample case.")
            return

        with st.spinner(f"Analyzing ({origin})…"):
            result = analyze(query, source_dir)

    except UnsafeUploadError as exc:
        st.error(f"Refused: {exc}")
        return
    except Exception as exc:  # noqa: BLE001 - the page must not die on a workflow error
        st.error(f"Analysis failed: {exc}")
        return

    st.session_state["result"] = result
    st.session_state["source_dir"] = str(source_dir)
    st.session_state["origin"] = origin


def _render_analysis(result: dict) -> None:
    answer = result.get("final_answer") or {}

    status = answer.get("status", "unknown")
    left, right = st.columns([3, 1])
    left.subheader(STATUS_LABELS.get(status, status))
    right.metric("Confidence", answer.get("overall_confidence", 0.0))

    st.caption(f"Intent: `{result.get('intent')}`  ·  Documents: {st.session_state.get('origin')}")
    st.markdown(f"**Summary.** {answer.get('summary') or '_none_'}")

    facts = answer.get("key_facts") or []
    if facts:
        st.markdown("#### Key facts")
        for fact in facts:
            icon = "✅" if fact.get("supported") else "⚠️"
            st.markdown(f"{icon} `{fact.get('confidence')}` {fact.get('text', '')}")

    verified = result.get("verified_claims") or []
    unsupported = result.get("unsupported_claims") or []
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"#### Verified claims ({len(verified)})")
        for claim in verified:
            with st.expander(f"✅ {claim.claim_id}"):
                st.write(claim.text)
                st.caption(
                    f"confidence {claim.confidence} · supported by "
                    f"{len(claim.supported_by)} chunk(s)"
                )
    with col_b:
        st.markdown(f"#### Unsupported ({len(unsupported)})")
        if not unsupported:
            st.caption("Nothing was left unverified.")
        for claim in unsupported:
            with st.expander(f"⚠️ {claim.claim_id}"):
                st.write(claim.text)
                st.caption(f"reason: {claim.uncertainty or 'no evidence found'}")

    actions = answer.get("actions") or []
    st.markdown(f"#### Actions ({len(actions)})")
    if not actions:
        st.caption("No action was drafted for this result.")
    for action in actions:
        payload = action.get("payload") or {}
        body = payload.get("body")
        title = f"{action.get('action_id')} — {action.get('description', '')}"
        if body:
            with st.expander(title):
                st.text_input("Draft subject", payload.get("subject", ""), disabled=True)
                st.text_area(
                    "Draft email",
                    body,
                    height=220,
                    disabled=True,
                    key=f"draft_{action.get('action_id')}",
                )
        else:
            st.markdown(f"- `{action.get('action_id')}` {action.get('description', '')}")

    chunks = result.get("retrieved_evidence") or []
    st.markdown(f"#### Evidence chunks ({len(chunks)})")
    for chunk in chunks:
        doc_type = chunk.metadata.get("doc_type")
        header = f"[{doc_type}] {chunk.source_id} · {chunk.chunk_id}"
        with st.expander(header):
            st.caption(f"trust {chunk.trust_score}")
            st.write(chunk.text)


def main() -> None:
    st.set_page_config(page_title="BuyWise Agent", page_icon="🛒", layout="wide")
    st.title("🛒 BuyWise Agent")
    st.caption(
        "Warranty / return analysis over your own documents. Local only — no external APIs, "
        "no account, nothing leaves this machine."
    )

    st.session_state.setdefault("query", DEFAULT_QUERY)

    uploaded, loaded_sample = _sidebar()
    if loaded_sample:
        # "Load sample" is a one-click shortcut: it loads the documents and the question that
        # was written for them. The key has to be set *before* the widget below is created —
        # Streamlit refuses a widget key written after instantiation.
        st.session_state["query"] = SAMPLE_QUERIES.get(loaded_sample, DEFAULT_QUERY)

    query = st.text_input("Your question", key="query")

    col_a, col_b = st.columns([1, 1])
    analyze = col_a.button("Analyze", type="primary", use_container_width=True)
    clear = col_b.button("Clear session", use_container_width=True)

    if clear:
        if st.session_state.get("session_id"):
            clear_session_dir(new_session_dir(st.session_state["session_id"]))
        for key in ("result", "source_dir", "origin", "session_id"):
            st.session_state.pop(key, None)
        st.rerun()

    # A sample button runs the analysis itself; only the free-form path needs "Analyze".
    if loaded_sample or analyze:
        _run(query, uploaded, loaded_sample)

    result = st.session_state.get("result")
    if result:
        st.divider()
        _render_analysis(result)
    else:
        st.info("Upload documents or load a sample case, then press **Analyze**.")


if __name__ == "__main__":
    main()
