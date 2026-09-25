"""Label/value extraction - keep a document's structure instead of re-guessing it later.

Policy documents are written as labelled lines: "Return Window: 14 days from delivery". What the
agents need is the *pairing* between a label and its value. Guessing that pairing out of flattened
prose means guessing at boundaries, which is how "Return Window:" once became a chunk of its own
and the number beside it ended up somewhere else. Reading the pairing while the structure still
exists (an HTML paragraph, a document line) makes it exact.

One implementation serves both callers, so there is a single definition of what a label is:
the HTML parser applies it per block, and the policy agent falls back to it for formats whose
structure is already gone (plain text, email bodies).
"""

from __future__ import annotations

import re

# A label is a short run of words ending in a colon at the start of a line or block. Kept
# deliberately narrow — it must not swallow a sentence that merely happens to contain a colon.
_LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /&'()\-#_.]{1,40}?)\s*:\s*(\S.*)$")

# Values beyond this are almost certainly a mis-parse of prose, not a policy value.
MAX_VALUE_LEN = 500


def extract_labels(text: str) -> dict[str, str]:
    """Map each "Label: value" line to its value, keyed by a normalised label.

    Keys are lowercased and whitespace-collapsed so that lookups do not depend on how a given
    document chose to capitalise or space its headings. The first occurrence of a label wins.
    """
    labels: dict[str, str] = {}
    for line in text.splitlines():
        match = _LABEL_RE.match(line)
        if not match:
            continue
        key = " ".join(match.group(1).lower().split())
        if not key:
            continue
        value = match.group(2).strip()
        if not value or len(value) > MAX_VALUE_LEN:
            continue
        labels.setdefault(key, value)
    return labels


def merge_labels(chunks: list) -> dict[str, str]:
    """Collect labels across chunks, first occurrence winning.

    Carries each chunk's own labels (set by the parser from real document structure) and falls
    back to reading the raw text for formats that have none.
    """
    merged: dict[str, str] = {}
    for chunk in chunks:
        own = (getattr(chunk, "metadata", None) or {}).get("labels")
        found = dict(own) if own else extract_labels(chunk.text)
        for key, value in found.items():
            merged.setdefault(key, value)
    return merged


def get_label(labels: dict[str, str], *names: str) -> str | None:
    """First value among the given aliases, so callers need not guess a document's wording."""
    for name in names:
        value = labels.get(name)
        if value is not None:
            return value
    return None
