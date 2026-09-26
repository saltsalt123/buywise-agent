"""
PDF parser - extracts text and tables from PDF documents.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pdfplumber

from agent.state import EvidenceChunk, SourceDocument, hash_content, make_chunk_id
from ingestion.doc_type import infer_doc_type


def parse_pdf(
    file_path: str, user_id: str = "default"
) -> tuple[SourceDocument, list[EvidenceChunk]]:
    """Parse a PDF file into a SourceDocument + list of EvidenceChunks."""
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    file_hash = hash_content(raw_bytes)

    # Page text is read before the doc_type is decided so the shared inference can consult
    # the body when the filename says nothing (see ingestion/doc_type.py).
    with pdfplumber.open(path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]

    doc_type = infer_doc_type(path, "\n".join(page_texts))

    source = SourceDocument(
        source_id=f"src_{file_hash[:12]}",
        user_id=user_id,
        file_hash=file_hash,
        doc_type=doc_type,
        title=path.name,
        created_at=datetime.fromtimestamp(path.stat().st_mtime),
        metadata={"file_path": str(path), "pages": len(page_texts)},
    )

    chunks: list[EvidenceChunk] = []

    for page_num, text in enumerate(page_texts, start=1):
        # Split long pages into paragraph-level chunks
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            chunk = EvidenceChunk(
                chunk_id=make_chunk_id(source.source_id, page_num, None, i),
                source_id=source.source_id,
                text=para,
                page=page_num,
                metadata={"doc_type": doc_type.value},
            )
            chunks.append(chunk)

    source.metadata["chunk_count"] = len(chunks)
    return source, chunks
