"""Shared tokenisation and term weighting for evidence matching.

Both the retriever and the verifier need the same answer to "which words in this text
carry meaning?".  Keeping the answer in one place stops the two from drifting apart —
which is how the retriever ended up scoring a chunk by counting the word ``i`` and the
verifier ended up accepting a warranty period as support for a return window.

Terms are matched on token boundaries, never as substrings: ``"i"`` must not match
"delivery", and ``"return"`` must not match "returns".
"""

from __future__ import annotations

import math
import re

# Deliberately conservative: only words that carry no topical information.  Modal verbs
# such as "may" and "can" are included because in a query like "Can I return this laptop
# I bought on May 15?" they say nothing about the product or the policy.
STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been before being
    below between both but by can cannot could did do does doing down during each few for from
    further had has have having he her here hers him his how i if in into is it its just me may
    might more most must my no nor not of off on once only or other our ours out over own same
    should so some such than that the their theirs them then there these they this those through
    to too under until up very was we were what when where which while who whom why will with
    would you your yours
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens; punctuation and case are dropped."""
    return _TOKEN_RE.findall(text.lower())


def content_terms(text: str) -> set[str]:
    """Tokens that carry topical meaning (stopwords and single characters removed)."""
    return {t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1}


def numeric_terms(text: str) -> set[str]:
    """Tokens containing a digit — quantities a claim asserts and evidence must confirm."""
    return {t for t in tokenize(text) if any(ch.isdigit() for ch in t)}


def inverse_document_frequency(documents: list[set[str]], terms: set[str]) -> dict[str, float]:
    """Smoothed IDF over the supplied document token sets.

    A term the whole corpus contains (``return``, in a corpus of return policies) counts for
    little; a term only one document contains (``laptop``) counts for a lot.
    """
    total = max(len(documents), 1)
    df: dict[str, int] = {}
    for tokens in documents:
        for term in terms & tokens:
            df[term] = df.get(term, 0) + 1
    return {term: math.log(1 + total / (1 + df.get(term, 0))) for term in terms}
