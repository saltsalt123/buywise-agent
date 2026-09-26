"""
CSV parser - parses order/bank/review CSV files into structured records.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
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
from ingestion.doc_type import infer_doc_type


def parse_csv(
    file_path: str, user_id: str = "default"
) -> tuple[SourceDocument, list[EvidenceChunk], list[ParsedObject]]:
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    file_hash = hash_content(raw_bytes)
    name_lower = path.stem.lower()

    # doc_type comes from the shared inference (see ingestion/doc_type.py) so the rules live
    # in one place. object_type is specific to this parser and stays here.
    doc_type = infer_doc_type(path, "")
    if doc_type == DocType.REVIEWS:
        object_type = ParsedObjectType.REVIEW_ISSUE
    elif any(k in name_lower for k in ("bank", "transaction", "流水", "price", "history")):
        object_type = ParsedObjectType.TRANSACTION
    else:
        object_type = ParsedObjectType.ORDER

    source = SourceDocument(
        source_id=f"src_{file_hash[:12]}",
        user_id=user_id,
        file_hash=file_hash,
        doc_type=doc_type,
        title=path.name,
        created_at=datetime.fromtimestamp(path.stat().st_mtime),
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
