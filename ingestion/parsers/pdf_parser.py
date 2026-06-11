"""
PDF parser - extracts text and tables from PDF documents.
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber

from agent.state import DocType, EvidenceChunk, SourceDocument, hash_content, make_chunk_id


def parse_pdf(file_path: str, user_id: str = "default") -> tuple[SourceDocument, list[EvidenceChunk]]:
    """Parse a PDF file into a SourceDocument + list of EvidenceChunks."""
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    file_hash = hash_content(raw_bytes)

    # Infer doc type from filename keywords
    name_lower = path.stem.lower()
    if "warranty" in name_lower:
        doc_type = DocType.WARRANTY
    elif "receipt" in name_lower or "order" in name_lower:
        doc_type = DocType.RECEIPT
    elif "manual" in name_lower or "guide" in name_lower:
        doc_type = DocType.MANUAL
    elif "policy" in name_lower or "return" in name_lower:
        doc_type = DocType.POLICY
    else:
        doc_type = DocType.MANUAL

    source = SourceDocument(
        source_id=f"src_{file_hash[:12]}",
        user_id=user_id,
        file_hash=file_hash,
        doc_type=doc_type,
        title=path.name,
        created_at=path.stat().st_ctime,  # rough
        metadata={"file_path": str(path), "pages": 0},
    )

    chunks: list[EvidenceChunk] = []

    with pdfplumber.open(path) as pdf:
        source.metadata["pages"] = len(pdf.pages)
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = page.extract_tables()

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
