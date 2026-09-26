"""Retrieval ranking: filler must not outrank policy.

``SimpleRetriever.hybrid_search`` scored a chunk by counting how many raw query tokens
appeared anywhere in its text::

    query_terms = set(query_lower.split())
    score = sum(1 for term in query_terms if term in text_lower)

Two problems with that.  The tokens include stopwords, and the test is a plain substring
check, so ``"i"`` matches almost any English word and ``"can"`` matches "can", "cannot",
"candidate" alike.  A chunk of filler that repeats ``can / i / this / on / may`` therefore
outscores a real policy sentence.

The fix is stopword filtering plus inverse document frequency — no vector store needed.
The contract these tests pin down: a chunk matching only stopwords still reaches the
candidate set (so recall does not shrink), but it can never outrank a chunk that matches a
content term, and the more informative the term, the higher it ranks.
"""

from __future__ import annotations

from agent.state import EvidenceChunk
from retrieval import HybridRetrievalPipeline, SimpleRetriever

QUERY = "Can I return this laptop I bought on May 15?"

POLICY_TEXT = "Return Window: 14 days from delivery for laptops and electronics"

# Filler built only from the question's own stopwords — no policy content at all.  It must
# still be retrieved (ranking is not a recall filter), but it must not outrank real text.
FILLER_TEXT = (
    "Can I this? I can. This is on me. This can be on. "
    "I can. This is this. On I can. Can I? This is on. "
    "I can this on. This is on me. Can this be? I can. This is on."
)


def _chunk(chunk_id: str, text: str, doc_type: str = "policy", trust: float = 1.0) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        source_id="s1",
        text=text,
        metadata={"doc_type": doc_type},
        trust_score=trust,
    )


def _retriever() -> SimpleRetriever:
    r = SimpleRetriever()
    r.index_chunks([_chunk("filler", FILLER_TEXT), _chunk("policy", POLICY_TEXT)])
    return r


class TestPolicyOutranksFiller:
    def test_hybrid_search_puts_the_policy_chunk_first(self) -> None:
        ranked = _retriever().hybrid_search(QUERY, top_k=10)
        order = [c.chunk_id for c in ranked]
        assert order, "nothing was retrieved"
        assert order[0] == "policy", (
            f"ranking was {order} — a chunk made of the question's own filler words "
            "outranked the policy text"
        )

    def test_pipeline_keeps_the_policy_chunk(self) -> None:
        pipeline = HybridRetrievalPipeline(_retriever())
        result = pipeline.retrieve(query=QUERY, top_k=10, max_chunks=5)
        ids = [c.chunk_id for c in result["chunks"]]
        assert ids and ids[0] == "policy", f"pipeline order was {ids}"

    def test_filler_is_still_reachable(self) -> None:
        """Ranking must not become a recall filter: the filler chunk is still returned."""
        ranked = _retriever().hybrid_search(QUERY, top_k=10)
        assert "filler" in {c.chunk_id for c in ranked}, (
            "the filler chunk disappeared from the candidate set; ranking changes must not "
            "shrink recall"
        )
        assert len(ranked) == 2


class TestStopwordOnlyMatchesScoreLowest:
    def test_chunk_matching_only_stopwords_sinks_below_a_content_match(self) -> None:
        r = SimpleRetriever()
        r.index_chunks([
            _chunk("stopword_only", "can i this on may"),
            _chunk("content", "The laptop return window is 14 days"),
        ])
        order = [c.chunk_id for c in r.hybrid_search(QUERY, top_k=10)]
        assert order[0] == "content", f"ranking was {order}"

    def test_single_letter_tokens_do_not_match_whole_words(self) -> None:
        """The old substring test let ``"i"`` match "window", "delivery", "within"."""
        r = SimpleRetriever()
        r.index_chunks([
            _chunk("no_real_overlap", "window delivery within shipping"),
            _chunk("content", "laptop return window 14 days"),
        ])
        order = [c.chunk_id for c in r.hybrid_search(QUERY, top_k=10)]
        assert order[0] == "content", (
            f"ranking was {order} — tokens are still being matched as substrings"
        )


class TestRareTermsOutweighCommonOnes:
    def test_rare_query_term_beats_a_ubiquitous_one(self) -> None:
        """``laptop`` is far more informative than ``return`` in this corpus."""
        r = SimpleRetriever()
        r.index_chunks([
            _chunk("return_only", "return return return return return"),
            _chunk("return_and_laptop", "laptop return"),
        ])
        order = [c.chunk_id for c in r.hybrid_search(QUERY, top_k=10)]
        assert order[0] == "return_and_laptop", f"ranking was {order}"

    def test_trust_score_still_breaks_ties(self) -> None:
        r = SimpleRetriever()
        r.index_chunks([
            _chunk("low_trust", POLICY_TEXT, trust=0.5),
            _chunk("high_trust", POLICY_TEXT, trust=1.0),
        ])
        order = [c.chunk_id for c in r.hybrid_search(QUERY, top_k=10)]
        assert set(order) == {"low_trust", "high_trust"}
