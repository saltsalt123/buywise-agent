"""
CSV parser - parses order/bank/review CSV files into structured records.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from agent.state import (
    DocType,
    EvidenceChunk,
    ParsedObject,
    ParsedObjectType,
    SourceDocument,
    hash_content,
    make_chunk_id,
)


def parse_csv(file_path: str, user_id: str = "default") -> tuple[SourceDocument, list[EvidenceChunk], list[ParsedObject]]:
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    file_hash = hash_content(raw_bytes)
    name_lower = path.stem.lower()

    # Infer type
    if "review" in name_lower or "comment" in name_lower:
        doc_type = DocType.REVIEWS
        object_type = ParsedObjectType.REVIEW_ISSUE
    elif "bank" in name_lower or "transaction" in name_lower or "流水" in name_lower:
        doc_type = DocType.BANK_CSV
        object_type = ParsedObjectType.TRANSACTION
    elif "price" in name_lower or "history" in name_lower:
        doc_type = DocType.BANK_CSV
        object_type = ParsedObjectType.TRANSACTION
    else:
        doc_type = DocType.BANK_CSV
        object_type = ParsedObjectType.ORDER

    source = SourceDocument(
        source_id=f"src_{file_hash[:12]}",
        user_id=user_id,
        file_hash=file_hash,
        doc_type=doc_type,
        title=path.name,
        metadata={"file_path": str(path)},
    )

    chunks: list[EvidenceChunk] = []
    parsed_objects: list[ParsedObject] = []

    content = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    for row_idx, row in enumerate(reader):
        text = " | ".join(f"{k}: {v}" for k, v in row.items() if v)
        chunk = EvidenceChunk(
            chunk_id=make_chunk_id(source.source_id, None, str(row_idx), row_idx),
            source_id=source.source_id,
            text=text,
            row_id=str(row_idx),
            metadata={"doc_type": doc_type.value, "row": row_idx},
        )
        chunks.append(chunk)

        parsed = ParsedObject(
            object_id=f"obj_{file_hash[:12]}_r{row_idx}",
            source_id=source.source_id,
            object_type=object_type,
            fields=row,
            evidence_chunk_ids=[chunk.chunk_id],
        )
        parsed_objects.append(parsed)

    source.metadata["row_count"] = len(chunks)
    return source, chunks, parsed_objects
