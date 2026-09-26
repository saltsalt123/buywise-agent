"""Upload handling for the Streamlit UI — plain functions, no Streamlit import.

Kept separate from ``streamlit_app.py`` so the path rules can be tested without a browser,
a server, or streamlit installed: the module that decides what a user-supplied name may
become is exactly the module that should not need a UI framework to exercise.

A file name arriving from a browser is untrusted input, not a path. It is treated as a name
and nothing else — anything carrying a directory component is refused rather than silently
flattened to its basename, because a silent rewrite hides an attempt instead of reporting it.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

from agent.graph import run_workflow
from apps.safe_paths import (
    SAMPLE_DATA_ROOT,
    UPLOAD_ROOT,
    UnsafeUploadError,
    is_within_safe_roots,
    resolve_within_safe_roots,
)

__all__ = [
    "ALLOWED_UPLOAD_EXTENSIONS",
    "SAMPLE_CASES",
    "UnsafeUploadError",
    "analyze",
    "new_session_dir",
    "safe_upload_target",
    "sample_case_path",
    "save_uploads",
]

# The extensions the ingestion layer can parse (txt/pdf/csv/eml/html — .htm is accepted as
# the same document as .html).
ALLOWED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset({".txt", ".pdf", ".csv", ".eml", ".html"})

# Fixed table, never built from user text: a traversal string can only ever miss a lookup.
SAMPLE_CASES: dict[str, Path] = {
    "headphone": SAMPLE_DATA_ROOT / "headphone_warranty_case",
    "laptop": SAMPLE_DATA_ROOT / "laptop_return_case",
}


def new_session_dir(session_id: str | None = None) -> Path:
    """Create (or reuse) ``data/uploads/session_<id>`` and return it.

    A stable ``session_id`` matters: Streamlit re-runs the whole script on every widget
    interaction, so a fresh id per run would orphan the files uploaded a moment earlier.
    """
    name = "session_" + (session_id or uuid.uuid4().hex)
    session = UPLOAD_ROOT / name
    session.mkdir(parents=True, exist_ok=True)

    # The UI is the component that creates directories, so it is the component that must
    # check it created the right one.
    resolved = session.resolve()
    if not is_within_safe_roots(resolved):
        raise UnsafeUploadError(f"refusing to use {resolved}, which is outside the safe roots")
    return resolved


def clear_session_dir(session_dir: Path | str) -> None:
    """Remove a session directory, refusing anything outside the upload root."""
    resolved = Path(session_dir).resolve()
    if resolved == UPLOAD_ROOT.resolve() or not resolved.is_relative_to(UPLOAD_ROOT.resolve()):
        raise UnsafeUploadError(f"refusing to delete {resolved}")
    shutil.rmtree(resolved, ignore_errors=True)


def safe_upload_target(session_dir: Path | str, filename: str) -> Path:
    """Return where ``filename`` may be written inside ``session_dir``.

    Refuses: an empty name, a name with any directory component (``../x``, ``sub/x``,
    ``/etc/x``), a missing or disallowed extension, and a name whose *resolved* path leaves
    the session (a symlink planted earlier in the session, for instance).
    """
    session = Path(session_dir).resolve()
    if not session.is_dir():
        raise UnsafeUploadError(f"session directory {session} does not exist")

    name = (filename or "").strip()
    if not name:
        raise UnsafeUploadError("file name is empty")
    if name in {".", ".."} or Path(name).name != name:
        raise UnsafeUploadError(
            f"file name {filename!r} contains a path component; only a plain file name is allowed"
        )

    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise UnsafeUploadError(
            f"{name!r} has extension {suffix or '(none)'!r}; allowed: {allowed}"
        )

    target = session / name
    resolved = target.resolve()
    inside = resolved.parent == session or session in resolved.parents
    if resolved != target or not inside:
        raise UnsafeUploadError(f"{name!r} resolves to {resolved}, outside the session")
    return target


def save_uploads(
    session_dir: Path | str, files: Iterable[tuple[str, bytes]]
) -> list[Path]:
    """Write ``(name, data)`` pairs into the session directory, returning the paths.

    Every target is validated *before* anything is written: a batch that fails halfway would
    leave a session directory that looks usable but is missing part of what the user sent.
    """
    session = Path(session_dir).resolve()
    pending = [(name, data, safe_upload_target(session, name)) for name, data in files]

    written: list[Path] = []
    for _name, data, target in pending:
        target.write_bytes(data)
        written.append(target)
    return written


def sample_case_path(name: str) -> Path:
    """Resolve a sample-case shortcut from the fixed table."""
    try:
        path = SAMPLE_CASES[name]
    except (KeyError, TypeError):
        known = ", ".join(sorted(SAMPLE_CASES))
        raise UnsafeUploadError(f"unknown sample case {name!r}; known cases: {known}") from None

    if not path.is_dir():
        raise UnsafeUploadError(f"sample case {name!r} is missing from the repository ({path})")
    return path


def analyze(query: str, source_dir: Path | str, user_id: str = "default") -> dict:
    """Run the workflow over ``source_dir``, insisting the directory is safe first.

    The workflow itself will read whatever directory it is handed, so the check belongs here,
    at the edge where a user-influenced path enters.
    """
    resolved = resolve_within_safe_roots(source_dir)
    return run_workflow(query, [str(resolved)], user_id=user_id)
