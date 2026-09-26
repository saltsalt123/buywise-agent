"""
HTML parser - extracts clean content from product pages and policy pages.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, Comment

from agent.state import (
    EvidenceChunk,
    ParsedObject,
    ParsedObjectType,
    SourceDocument,
    hash_content,
    make_chunk_id,
)
from ingestion.doc_type import infer_doc_type
from ingestion.labels import extract_labels

# Tags to remove as boilerplate
BOILERPLATE_TAGS = [
    "script", "style", "nav", "footer", "header",
    "aside", "noscript", "iframe", "form", "button",
]

# Inline markup carries no line-break semantics, but `get_text(separator="\n")` inserts a
# separator between *every* element. So "<p><strong>Return Window:</strong> 14 days from
# delivery</p>" came out as two lines, and since this parser chunks one line per chunk, the
# label ended up in a chunk without its value. Unwrapping these first keeps a paragraph whole.
INLINE_TAGS = [
    "strong", "b", "em", "i", "u", "span", "a", "small", "code",
    "abbr", "cite", "mark", "sub", "sup", "label", "time",
]


def clean_html(html: str) -> str:
    """Strip boilerplate HTML elements and return clean text."""
    soup = BeautifulSoup(html, "lxml")

    # Remove boilerplate tags
    for tag in BOILERPLATE_TAGS:
        for el in soup.find_all(tag):
            el.decompose()

    # Remove comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Remove hidden elements
    for el in soup.find_all(style=True):
        style = el.get("style", "")
        if "display:none" in style or "visibility:hidden" in style:
            el.decompose()

    # Flatten inline markup before text extraction; see INLINE_TAGS. Unwrapping alone is not
    # enough: it turns the tag into text but leaves that text as its own node, and get_text
    # still separates adjacent nodes. smooth() merges them so a paragraph reads as one line.
    for tag in INLINE_TAGS:
        for el in soup.find_all(tag):
            el.unwrap()
    soup.smooth()

    # Keep only main/product/review/policy areas if they exist
    main = soup.find("main") or soup.find(
        "div", class_=lambda c: c and any(
            kw in (c or "").lower()
            for kw in ["content", "product", "review", "policy", "main"]
        )
    )
    if main:
        text = main.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)

    # Deduplicate empty lines
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def parse_html(
    file_path: str, user_id: str = "default"
) -> tuple[SourceDocument, list[EvidenceChunk], list[ParsedObject]]:
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    file_hash = hash_content(raw_bytes)

    # The text is cleaned before the doc_type is decided so the shared inference can consult
    # the body when the filename says nothing (see ingestion/doc_type.py).
    raw_html = raw_bytes.decode("utf-8", errors="replace")
    clean_text = clean_html(raw_html)
    doc_type = infer_doc_type(path, clean_text)

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
    paragraphs = [p.strip() for p in clean_text.split("\n") if p.strip()]

    for i, para in enumerate(paragraphs):
        # Capture the label/value pairing while the block structure is still known. Downstream
        # agents otherwise have to re-guess it from flattened prose, which is how a label once
        # came to be read without the value beside it.
        labels = extract_labels(para)
        chunk = EvidenceChunk(
            chunk_id=make_chunk_id(source.source_id, None, None, i),
            source_id=source.source_id,
            text=para[:2000],
            metadata={"doc_type": doc_type.value, "labels": labels},
        )
        chunks.append(chunk)

        if labels:
            parsed_objects.append(
                ParsedObject(
                    object_id=f"obj_{file_hash[:12]}_c{i}",
                    source_id=source.source_id,
                    object_type=ParsedObjectType.POLICY_RULE,
                    fields=labels,
                    evidence_chunk_ids=[chunk.chunk_id],
                )
            )

    source.metadata["chunk_count"] = len(chunks)
    return source, chunks, parsed_objects
