"""Which directories may be read, in one place.

Two entry points now hand document paths to the workflow: the HTTP API (``source_dirs`` from
a request body) and the Streamlit UI (a directory it just wrote uploaded files into). They
must agree — a directory the UI writes but the API refuses would be a broken UI, and a
directory the UI accepts but nothing validates would be the file-disclosure bug back again.

So the roots live here, and both callers import them. ``resolve()`` runs before every
comparison, so a symlink or ``..`` cannot be used to step outside a root.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Bundled demo documents.
SAMPLE_DATA_ROOT = PROJECT_ROOT / "sample_data"

# Where the UI writes uploaded files, one directory per browser session. `.gitignore` keeps
# the contents out of version control.
UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"

SAFE_SOURCE_ROOTS: tuple[Path, ...] = (SAMPLE_DATA_ROOT, UPLOAD_ROOT)


class UnsafeUploadError(ValueError):
    """A path or file name was refused.

    Raised for anything the caller must not be allowed to read or write: a traversal, an
    absolute path, a disallowed extension, or a name that resolves outside the directory it
    was meant to land in. Callers translate it into their own error (the API returns 400).
    """


def is_within_safe_roots(path: Path | str) -> bool:
    """True when ``path`` resolves to a safe root or something inside one."""
    resolved = Path(path).resolve()
    return any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve())
        for root in SAFE_SOURCE_ROOTS
    )


def resolve_within_safe_roots(path: Path | str) -> Path:
    """Resolve ``path`` and return it, or raise if it is outside the safe roots.

    Relative paths are taken from the project root.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    if not is_within_safe_roots(resolved):
        roots = ", ".join(str(root.resolve()) for root in SAFE_SOURCE_ROOTS)
        raise UnsafeUploadError(f"{str(path)!r} is outside the allowed roots ({roots})")
    return resolved
