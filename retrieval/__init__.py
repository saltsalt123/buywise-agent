"""
Retrieval layer - hybrid search with BM25 + metadata filtering + reranking + compression.
"""
from __future__ import annotations

from typing import Any

from agent.state import EvidenceChunk
from agent.textnorm import content_terms, inverse_document_frequency, tokenize


class SimpleRetriever:
    """Simple in-memory retriever with BM25 and metadata filtering.
    In production, this wraps pgvector + BM25 index + reranker.
    """

    def __init__(self):
        self._chunks: list[EvidenceChunk] = []

    def index_chunks(self, chunks: list[EvidenceChunk]):
        """Load chunks into the retriever."""
        self._chunks = chunks

    def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[EvidenceChunk]:
        """Keyword search, ranked by IDF-weighted content overlap.

        Ranking used to be a plain substring count over raw query tokens, so a chunk made
        of the question's own filler ("can", "i", "this", "on", "may") outscored a real
        policy sentence, and a single "i" matched almost every English word.

        Now the primary score is the summed IDF of the *content* terms a chunk contains —
        stopwords contribute nothing, and a rare term counts for more than a common one.
        Two secondary signals keep recall intact: the number of raw query tokens present,
        and the legacy substring count, both used only as tie-breakers and as the
        inclusion test.  A chunk that matched before still matches; it just cannot outrank
        a chunk that answers the question.
        """
        candidates: list[EvidenceChunk] = []
        for chunk in self._chunks:
            if metadata_filter:
                matched = True
                for key, value in metadata_filter.items():
                    if chunk.metadata.get(key) != value:
                        matched = False
                        break
                if not matched:
                    continue
            candidates.append(chunk)

        query_tokens = tokenize(query)
        raw_terms = set(query_tokens)
        terms_of_interest = content_terms(query) | {t for t in raw_terms if len(t) > 1}

        chunk_tokens = [(c, set(tokenize(c.text))) for c in candidates]
        idf = inverse_document_frequency([toks for _, toks in chunk_tokens], terms_of_interest)

        scored: list[tuple[EvidenceChunk, float, int, int]] = []
        for chunk, tokens in chunk_tokens:
            content_score = sum(
                idf[term] for term in content_terms(query) if term in tokens
            )
            raw_score = len(raw_terms & tokens)
            substring_score = sum(1 for term in raw_terms if term in chunk.text.lower())
            if content_score <= 0 and raw_score <= 0 and substring_score <= 0:
                continue
            scored.append((chunk, content_score, raw_score, substring_score))

        scored.sort(
            key=lambda item: (item[1], item[2], item[3], item[0].trust_score),
            reverse=True,
        )
        return [chunk for chunk, *_ in scored[:top_k]]

    def rerank(self, chunks: list[EvidenceChunk], query: str) -> list[EvidenceChunk]:
        """Simple reranking: prefer chunks with exact phrase matches and higher trust scores."""
        query_lower = query.lower()
        # Give priority to chunks containing the exact query phrase
        exact_matches = [c for c in chunks if query_lower in c.text.lower()]
        others = [c for c in chunks if c not in exact_matches]

        # Within each group, sort by trust_score descending
        exact_matches.sort(key=lambda c: c.trust_score, reverse=True)
        others.sort(key=lambda c: c.trust_score, reverse=True)

        return exact_matches + others

    def compress(
        self, chunks: list[EvidenceChunk], query: str, max_chunks: int = 5
    ) -> list[EvidenceChunk]:
        """Contextual compression: keep only top-k after reranking."""
        reranked = self.rerank(chunks, query)
        return reranked[:max_chunks]


class HybridRetrievalPipeline:
    """Full retrieval pipeline: metadata filter → hybrid search → rerank → compress → cite."""

    def __init__(self, retriever: SimpleRetriever | None = None):
        self.retriever = retriever or SimpleRetriever()

    def retrieve(
        self,
        query: str,
        metadata_filter: dict[str, Any] | None = None,
        top_k: int = 10,
        max_chunks: int = 5,
    ) -> dict:
        """
        Full retrieval pipeline.

        Returns:
        dict with:
          - chunks: list of EvidenceChunk (final compressed set)
          - chunk_count: int
          - sources: list of source_ids
        """
        # 1. Hybrid search
        results = self.retriever.hybrid_search(
            query=query,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )

        # 2. Rerank
        results = self.retriever.rerank(results, query)

        # 3. Compress
        results = self.retriever.compress(results, query, max_chunks=max_chunks)

        # 4. Collect source IDs
        source_ids = list({c.source_id for c in results})

        return {
            "chunks": results,
            "chunk_count": len(results),
            "sources": source_ids,
        }
