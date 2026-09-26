"""Parser robustness: real file formats, empty files, corrupt files, and partial failures.

``_load_sample_data`` catches an exception per file and only logs a warning, which is the
right call for a batch ingest but means a broken parser is invisible unless something looks.
It has already happened twice in this project: a missing import dropped every
pdf/csv/eml/html file, and a change to ``parse_html``'s return arity dropped every html
file.  Neither surfaced as a failure.

These tests exercise each format for real (the PDF is generated, not faked), and pin the
partial-failure contract: a single unreadable file must be logged and skipped, and must not
take the rest of the directory with it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from agent.graph import _load_sample_data, run_workflow

# reportlab is a hard import, deliberately not importorskip: a module-level `importorskip`
# turns a missing dependency into a single silent skip for the whole file — which is how this
# suite stopped running on a fresh install. reportlab was never declared as a dependency, so
# the 14 tests below vanished with nothing but "1 skipped" to show for it. It is now in the
# `dev` extra, and a missing dep fails loudly.

RECEIPT_TXT = (
    "TECHWORLD INC. - SALES RECEIPT\n"
    "Date: 2026-05-15 16:20:00\n"
    "Total: $1,299.00\n"
    "Return Policy: 30 days from purchase date\n"
)

BANK_CSV = (
    "date,description,amount,balance\n"
    "2026-05-15,TECHWORLD INC PURCHASE,-1299.00,3421.55\n"
    "2026-05-16,TECHWORLD INC REFUND,1299.00,4720.55\n"
)

POLICY_HTML = (
    '<html><body><div class="return-policy">'
    "<h1>TechWorld Return Policy</h1>"
    "<p><strong>Return Window:</strong> 14 days from delivery for laptops</p>"
    "<p><strong>Condition:</strong> Item must be in original packaging</p>"
    "</div></body></html>"
)

EMAIL_EML = """From: support@techworld.example
To: customer@email.example
Subject: Re: Warranty question for order ORD-20260515-3342
Date: Wed, 20 May 2026 09:12:00 +0800

Hello,

Your PowerBook Pro is covered by a 1 year manufacturer warranty from the purchase date.

Best regards,
TechWorld Support
"""


def _write_pdf(path: Path, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path))
    y = 760
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 18
    pdf.save()


@pytest.fixture()
def mixed_dir(tmp_path: Path) -> Path:
    target = tmp_path / "mixed"
    target.mkdir()
    (target / "receipt.txt").write_text(RECEIPT_TXT)
    (target / "bank_statement.csv").write_text(BANK_CSV)
    (target / "return_policy.html").write_text(POLICY_HTML)
    (target / "support_email.eml").write_text(EMAIL_EML)
    _write_pdf(
        target / "warranty_card.pdf",
        ["SOUNDMAX PRO - LIMITED WARRANTY CARD",
         "WARRANTY PERIOD: 1 YEAR from date of purchase",
         "COVERAGE: Manufacturer defects in materials"],
    )
    return target


class TestEveryFormatIsIngested:
    def test_all_five_formats_produce_chunks(self, mixed_dir: Path) -> None:
        chunks = _load_sample_data([str(mixed_dir)])
        assert chunks, "the mixed directory produced no chunks at all"

        doc_types = {c.metadata.get("doc_type") for c in chunks}
        assert doc_types == {"receipt", "bank_csv", "policy", "email", "warranty"}, (
            f"some formats were dropped: got {sorted(str(t) for t in doc_types)}"
        )

    def test_sources_are_attributed_per_file(self, mixed_dir: Path) -> None:
        chunks = _load_sample_data([str(mixed_dir)])
        source_ids = {c.source_id for c in chunks}
        assert len(source_ids) == 5, f"expected one source per file, got {len(source_ids)}"

    def test_pdf_text_is_extracted(self, mixed_dir: Path) -> None:
        chunks = _load_sample_data([str(mixed_dir / "warranty_card.pdf")])
        text = " ".join(c.text for c in chunks)
        assert "1 YEAR" in text, f"pdf text not extracted: {text[:200]!r}"


class TestEmptyFiles:
    def test_zero_byte_file_produces_no_chunks_and_does_not_raise(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.txt"
        empty.write_text("")
        assert _load_sample_data([str(empty)]) == []

    def test_workflow_survives_an_empty_file(self, tmp_path: Path) -> None:
        target = tmp_path / "only_empty"
        target.mkdir()
        (target / "receipt.txt").write_text("")
        result = run_workflow("Can I return this laptop?", [str(target)])
        answer = result.get("final_answer") or {}
        assert answer.get("status") in {"no_evidence", "insufficient_evidence"}

    def test_empty_file_does_not_hide_a_good_neighbour(self, tmp_path: Path) -> None:
        target = tmp_path / "empty_plus_good"
        target.mkdir()
        (target / "empty_receipt.txt").write_text("")
        (target / "real_receipt.txt").write_text(RECEIPT_TXT)
        chunks = _load_sample_data([str(target)])
        assert chunks, "the good file was lost because a sibling was empty"
        assert any("2026-05-15" in c.text for c in chunks)


class TestCorruptFiles:
    @pytest.fixture()
    def corrupt_dir(self, tmp_path: Path) -> Path:
        target = tmp_path / "corrupt"
        target.mkdir()
        (target / "broken.pdf").write_bytes(b"this is not a pdf at all")
        (target / "receipt.txt").write_text(RECEIPT_TXT)
        return target

    def test_corrupt_file_is_logged_not_swallowed(self, corrupt_dir: Path, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="agent.graph"):
            _load_sample_data([str(corrupt_dir)])
        messages = [r.getMessage() for r in caplog.records]
        assert any("broken.pdf" in m for m in messages), (
            f"a corrupt file was dropped with no record; captured: {messages}"
        )

    def test_corrupt_file_does_not_block_its_neighbour(self, corrupt_dir: Path) -> None:
        chunks = _load_sample_data([str(corrupt_dir)])
        assert chunks, "one corrupt file took the whole directory down"
        assert any("2026-05-15" in c.text for c in chunks), (
            "the healthy file in the same directory was not ingested"
        )

    def test_unknown_extension_is_skipped_quietly(self, tmp_path: Path) -> None:
        target = tmp_path / "unknown"
        target.mkdir()
        (target / "notes.xyz").write_bytes(b"\x00\x01\x02")
        (target / "receipt.txt").write_text(RECEIPT_TXT)
        chunks = _load_sample_data([str(target)])
        assert all("notes.xyz" not in (c.metadata.get("labels") or {}) for c in chunks)
        assert chunks, "the known file should still be ingested"

    def test_workflow_survives_a_directory_of_only_corrupt_files(self, tmp_path: Path) -> None:
        target = tmp_path / "all_bad"
        target.mkdir()
        (target / "a.pdf").write_bytes(b"garbage")
        (target / "b.pdf").write_bytes(b"more garbage")
        result = run_workflow("Can I return this laptop?", [str(target)])
        answer = result.get("final_answer") or {}
        assert answer.get("status") in {"no_evidence", "insufficient_evidence"}
        assert answer.get("overall_confidence") == 0.0


class TestHtmlInlineLabels:
    """An inline element must not split a label from its value."""

    def test_inline_strong_keeps_label_and_value_in_one_chunk(self, tmp_path: Path) -> None:
        target = tmp_path / "html"
        target.mkdir()
        (target / "return_policy.html").write_text(POLICY_HTML)
        chunks = _load_sample_data([str(target)])
        assert chunks

        holding = [c for c in chunks if (c.metadata.get("labels") or {}).get("return window")]
        assert holding, f"the inline label was not captured: {[c.text for c in chunks]}"
        chunk = holding[0]
        assert "14 days" in chunk.text, (
            f"the value was split away from its label: {chunk.text!r}"
        )
        assert chunk.metadata["labels"]["return window"].startswith("14 days")

    def test_label_and_value_never_land_in_different_chunks(self, tmp_path: Path) -> None:
        target = tmp_path / "html2"
        target.mkdir()
        (target / "return_policy.html").write_text(POLICY_HTML)
        chunks = _load_sample_data([str(target)])
        orphan_values = [
            c.text for c in chunks
            if c.text.strip().lower().startswith("14 days")
        ]
        assert not orphan_values, f"a value was separated from its label: {orphan_values}"

    @pytest.mark.parametrize(
        "markup,label",
        [
            ("<p><strong>Return Window:</strong> 14 days</p>", "return window"),
            ("<p><b>Refund:</b> Full refund in 5-10 days</p>", "refund"),
            ("<p><span>Condition:</span> Unused and boxed</p>", "condition"),
        ],
    )
    def test_various_inline_wrappers(self, tmp_path: Path, markup: str, label: str) -> None:
        target = tmp_path / f"wrap_{label.replace(' ', '_')}"
        target.mkdir()
        (target / "return_policy.html").write_text(f"<html><body>{markup}</body></html>")
        chunks = _load_sample_data([str(target)])
        found = {k.lower() for c in chunks for k in (c.metadata.get("labels") or {})}
        assert label in found, f"{label!r} not captured from {markup!r}; got {found}"
