"""
Email (.eml) parser - extracts headers and body from email files.
"""
from __future__ import annotations

import email
from email import policy
from pathlib import Path

from agent.state import DocType, EvidenceChunk, SourceDocument, hash_content, make_chunk_id


def parse_eml(file_path: str, user_id: str = "default") -> tuple[SourceDocument, list[EvidenceChunk]]:
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    file_hash = hash_content(raw_bytes)

    source = SourceDocument(
        source_id=f"src_{file_hash[:12]}",
        user_id=user_id,
        file_hash=file_hash,
        doc_type=DocType.EMAIL,
        title=path.name,
        metadata={"file_path": str(path)},
    )

    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    headers = {
        "subject": msg["subject"] or "",
        "from": str(msg["from"]) if msg["from"] else "",
        "date": str(msg["date"]) if msg["date"] else "",
        "message_id": str(msg["message-id"]) if msg["message-id"] else "",
    }
    source.metadata.update(headers)

    chunks: list[EvidenceChunk] = []

    # Extract body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    body += (part.get_content() or "")
                except Exception:
                    body += "[unreadable part]"
            elif ctype == "text/html":
                try:
                    body += (part.get_content() or "") + "\n"
                except Exception:
                    pass
    else:
        body = msg.get_content() or ""

    # Split body into paragraphs
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        chunk = EvidenceChunk(
            chunk_id=make_chunk_id(source.source_id, None, None, i),
            source_id=source.source_id,
            text=para[:2000],
            metadata={
                "doc_type": "email",
                "subject": headers["subject"],
                "from": headers["from"],
                "date": headers["date"],
            },
        )
        chunks.append(chunk)

    source.metadata["chunk_count"] = len(chunks)
    return source, chunks
