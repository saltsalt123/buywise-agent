"""
HTML parser - extracts clean content from product pages and policy pages.
"""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, Comment

from agent.state import DocType, EvidenceChunk, SourceDocument, hash_content, make_chunk_id


# Tags to remove as boilerplate
BOILERPLATE_TAGS = [
    "script", "style", "nav", "footer", "header",
    "aside", "noscript", "iframe", "form", "button",
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
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)


def parse_html(file_path: str, user_id: str = "default") -> tuple[SourceDocument, list[EvidenceChunk]]:
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    file_hash = hash_content(raw_bytes)
    name_lower = path.stem.lower()

    if "policy" in name_lower or "return" in name_lower:
        doc_type = DocType.POLICY
    elif "product" in name_lower or "page" in name_lower:
        doc_type = DocType.PRODUCT_PAGE
    elif "review" in name_lower:
        doc_type = DocType.REVIEWS
    else:
        doc_type = DocType.PRODUCT_PAGE

    source = SourceDocument(
        source_id=f"src_{file_hash[:12]}",
        user_id=user_id,
        file_hash=file_hash,
        doc_type=doc_type,
        title=path.name,
        metadata={"file_path": str(path)},
    )

    raw_html = raw_bytes.decode("utf-8", errors="replace")
    clean_text = clean_html(raw_html)

    chunks: list[EvidenceChunk] = []
    paragraphs = [p.strip() for p in clean_text.split("\n") if p.strip()]

    for i, para in enumerate(paragraphs):
        chunk = EvidenceChunk(
            chunk_id=make_chunk_id(source.source_id, None, None, i),
            source_id=source.source_id,
            text=para[:2000],
            metadata={"doc_type": doc_type.value},
        )
        chunks.append(chunk)

    source.metadata["chunk_count"] = len(chunks)
    return source, chunks
