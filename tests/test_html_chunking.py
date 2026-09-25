"""HTML chunking: inline markup must not split a paragraph.

`get_text(separator="\\n")` inserts a separator between *every* element, and this parser emits
one chunk per line. So "<p><strong>Return Window:</strong> 14 days</p>" produced two chunks: a
label with no value, and a value with no label. A policy lookup would then match "Return Window:"
and never see the number next to it, or vice versa.

The sample policy page regressed to 11 chunks this way, five of them bare labels.
"""

from __future__ import annotations

from pathlib import Path

from ingestion.parsers.html_parser import parse_html


def _chunks_for(html: str, tmp_path: Path) -> list[str]:
    path = tmp_path / "policy.html"
    path.write_text(html)
    _, chunks, _ = parse_html(str(path))
    return [chunk.text for chunk in chunks]


class TestInlineMarkupDoesNotSplitParagraphs:
    def test_label_and_value_stay_together(self, tmp_path):
        """The shape the sample case uses: a bold label followed by its value."""
        html = (
            "<html><body><div class='policy'>"
            "<p><strong>Return Window:</strong> 14 days from delivery</p>"
            "</div></body></html>"
        )
        chunks = _chunks_for(html, tmp_path)
        assert "Return Window: 14 days from delivery" in chunks
        assert "Return Window:" not in chunks

    def test_every_inline_tag_is_flattened(self, tmp_path):
        for tag in ("strong", "b", "em", "i", "span", "a", "code", "u", "small"):
            html = (
                f"<html><body><div class='policy'>"
                f"<p>x <{tag}>y</{tag}> z</p></div></body></html>"
            )
            assert "x y z" in _chunks_for(html, tmp_path), tag

    def test_nested_inline_markup_is_flattened(self, tmp_path):
        html = (
            "<html><body><div class='policy'>"
            "<p><strong><em>Both</em></strong> tags</p></div></body></html>"
        )
        assert "Both tags" in _chunks_for(html, tmp_path)

    def test_block_elements_still_separate_chunks(self, tmp_path):
        """Flattening inline markup must not merge genuinely separate paragraphs."""
        html = (
            "<html><body><div class='policy'>"
            "<h1>Policy</h1><p>First rule</p><p>Second rule</p>"
            "</div></body></html>"
        )
        chunks = _chunks_for(html, tmp_path)
        assert "Policy" in chunks
        assert "First rule" in chunks
        assert "Second rule" in chunks


class TestRealSampleFile:
    SAMPLE = Path("sample_data/laptop_return_case/return_policy.html")

    def test_no_label_only_chunks(self):
        _, chunks, _ = parse_html(str(self.SAMPLE))
        texts = [chunk.text for chunk in chunks]
        assert not [text for text in texts if text.endswith(":")], texts

    def test_each_rule_is_one_whole_chunk(self):
        _, chunks, _ = parse_html(str(self.SAMPLE))
        texts = [chunk.text for chunk in chunks]
        assert "Return Window: 14 days from delivery for laptops and electronics" in texts
        assert "Restocking Fee: 15% restocking fee for opened laptops" in texts

    def test_return_window_is_parseable_from_the_html_alone(self):
        """The receipt states it too, but the policy page must stand on its own."""
        _, chunks, _ = parse_html(str(self.SAMPLE))
        joined = " ".join(chunk.text.lower() for chunk in chunks)
        assert "return window: 14 days" in joined
