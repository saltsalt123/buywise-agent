"""
Ingestion orchestrator - routes files to the right parser, handles chunking and embedding.
"""
from __future__ import annotations

from pathlib import Path

from agent.state import DocType, EvidenceChunk, ParsedObject, SourceDocument

from .parsers.pdf_parser import parse_pdf
from .parsers.csv_parser import parse_csv
from .parsers.email_parser import parse_eml
from .parsers.html_parser import parse_html


SUPPORTED_EXTENSIONS = {
    ".pdf": ("pdf", False),
    ".csv": ("csv", True),
    ".eml": ("email", False),
    ".html": ("html", False),
    ".htm": ("html", False),
}


def parse_file(file_path: str, user_id: str = "default") -> dict:
    """Parse any supported file type. Returns source, chunks, and optional parsed_objects."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {list(SUPPORTED_EXTENSIONS.keys())}")

    parser_type, has_objects = SUPPORTED_EXTENSIONS[ext]

    if parser_type == "pdf":
        source, chunks = parse_pdf(file_path, user_id)
        parsed_objects = []
    elif parser_type == "csv":
        source, chunks, parsed_objects = parse_csv(file_path, user_id)
    elif parser_type == "email":
        source, chunks = parse_eml(file_path, user_id)
        parsed_objects = []
    elif parser_type == "html":
        source, chunks = parse_html(file_path, user_id)
        parsed_objects = []
    else:
        raise ValueError(f"Unknown parser type: {parser_type}")

    return {
        "source": source,
        "chunks": chunks,
        "parsed_objects": parsed_objects,
    }


def chunk_text(text: str, source_id: str, chunk_size: int = 800, overlap: int = 100) -> list[EvidenceChunk]:
    """Simple text chunker with overlap."""
    chunks = []
    start = 0
    i = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end]
        chunk = EvidenceChunk(
            chunk_id=f"chk_{source_id[:8]}_i{i}",
            source_id=source_id,
            text=chunk_text,
        )
        chunks.append(chunk)
        start += chunk_size - overlap
        i += 1
    return chunks
