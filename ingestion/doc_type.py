"""One place that decides what kind of document a file is.

`doc_type` is load-bearing: `policy_agent` only reads chunks whose doc_type is in
``{warranty, policy, receipt}``.  Inference used to be duplicated inside each parser and, for
``.txt``, looked at the filename alone — so ``return_policy.txt`` became ``manual`` and the
return policy was silently absent from every decision.  Nothing raised; the answer was just
missing a document.

Resolution order, most specific signal first:

1. **Fixed by extension** — a ``.eml`` is an email whatever it contains.
2. **Filename keyword** — ``warranty_card.pdf`` is a warranty card.
3. **Content keyword** — ``notes.txt`` containing "Return Window: 14 days" is a policy.
4. **Extension default** — ``.pdf``/``.txt`` fall back to ``manual``, ``.html`` to
   ``product_page``, ``.csv`` to ``bank_csv``.

The filename deliberately outranks the content: a warranty card that mentions a return
window is still a warranty, and a receipt that quotes the policy is still a receipt.  Only
when the name says nothing does the body get a vote.

``.txt`` no longer defaults to ``manual`` before checking the name and the body; ``manual``
is now only the *last* resort, after both have been consulted.
"""

from __future__ import annotations

from pathlib import Path

from agent.state import DocType

# Step 1 — the extension alone settles these; content is not consulted.
_EXTENSION_FIXED: dict[str, DocType] = {
    ".eml": DocType.EMAIL,
}

# Step 4 — used only when neither the name nor the body identifies the document.
_EXTENSION_DEFAULTS: dict[str, DocType] = {
    ".pdf": DocType.MANUAL,
    ".txt": DocType.MANUAL,
    ".text": DocType.MANUAL,
    ".log": DocType.MANUAL,
    ".html": DocType.PRODUCT_PAGE,
    ".htm": DocType.PRODUCT_PAGE,
    ".csv": DocType.BANK_CSV,
    ".eml": DocType.EMAIL,
}

# Step 2 — ordered: the first group whose keyword appears in the filename wins.  Warranty is
# checked before policy so that ``warranty_policy.txt`` is a warranty document, and receipt
# before warranty so that ``receipt.txt`` stays a receipt even if it mentions a warranty.
#
# Deliberately absent: the bank/transaction/price/history keywords that `csv_parser` used to
# carry.  A ``.csv`` already resolves to ``bank_csv`` through the extension default, and
# listing those words here made ``purchase_history.txt`` and ``price_list.pdf`` resolve to
# ``bank_csv`` — a type nothing reads, decided at the filename stage, so the content rules
# below never ran and a policy inside such a file was silently ignored.
_FILENAME_RULES: tuple[tuple[DocType, tuple[str, ...]], ...] = (
    (DocType.RECEIPT, ("receipt", "invoice")),
    (DocType.WARRANTY, ("warranty",)),
    (DocType.POLICY, ("policy", "return", "refund")),
    (DocType.REVIEWS, ("review", "comment")),
    (DocType.PRODUCT_PAGE, ("product",)),
    (DocType.MANUAL, ("manual", "guide", "readme")),
)

# Step 3 — same ordering logic.  Phrases are listed roughly most-specific first for
# readability; membership is what decides, not position.
_CONTENT_RULES: tuple[tuple[DocType, tuple[str, ...]], ...] = (
    (
        DocType.WARRANTY,
        (
            "warranty period",
            "limited warranty",
            "manufacturer warranty",
            "warranty",
        ),
    ),
    (
        DocType.POLICY,
        (
            "return window",
            "return policy",
            "refund policy",
            "final sale",
            "sales are final",
            "no returns",
            "no refunds",
            "not returnable",
            "not accepted",
            "exchange only",
            "eligible for return",
            "cannot be returned",
            "refund",
            "return",
        ),
    ),
    (
        DocType.REVIEWS,
        ("star rating", "customer review", "verified purchase"),
    ),
)

DEFAULT_DOC_TYPE = DocType.MANUAL


def infer_doc_type(path: Path | str, text: str = "") -> DocType:
    """Return the doc_type for ``path``, using ``text`` when the filename is uninformative.

    ``text`` is optional so callers that must build a ``SourceDocument`` before extracting
    anything (see the pdf/html parsers) can still share the filename rules.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    fixed = _EXTENSION_FIXED.get(suffix)
    if fixed is not None:
        return fixed

    name = p.stem.lower()
    for doc_type, keywords in _FILENAME_RULES:
        if any(keyword in name for keyword in keywords):
            return doc_type

    haystack = (text or "").lower()
    if haystack:
        for doc_type, keywords in _CONTENT_RULES:
            if any(keyword in haystack for keyword in keywords):
                return doc_type

    return _EXTENSION_DEFAULTS.get(suffix, DEFAULT_DOC_TYPE)
