"""
Retrieval layer - hybrid search with BM25 + metadata filtering + reranking + compression.
"""
from __future__ import annotations

from typing import Any

from agent.state import EvidenceChunk


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
        """Simple keyword + metadata filter search."""
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        scored: list[tuple[EvidenceChunk, float]] = []

        for chunk in self._chunks:
            # Metadata filter
            if metadata_filter:
                matched = True
                for key, value in metadata_filter.items():
                    if chunk.metadata.get(key) != value:
                        matched = False
                        break
                if not matched:
                    continue

            # Keyword scoring
            text_lower = chunk.text.lower()
            score = sum(1 for term in query_terms if term in text_lower)
            # Bonus for term density
            if score > 0:
                score += (score / max(len(query_terms), 1)) * 5
                scored.append((chunk, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return [chunk for chunk, _ in scored[:top_k]]

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

    def compress(self, chunks: list[EvidenceChunk], query: str, max_chunks: int = 5) -> list[EvidenceChunk]:
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
