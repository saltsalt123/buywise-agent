"""Every sample file must actually reach the retriever.

`_load_sample_data` catches exceptions per file and only logs a warning, so a parser whose
signature changed silently drops its documents instead of failing the run. That is not
hypothetical: a missing import once dropped every .pdf/.csv/.eml/.html file here, and a later
change to parse_html\'s return arity dropped every .html file again. Neither was visible, because
each case still resolved its values from another document and the eval stayed green.

These tests assert the files arrive, not that a case happens to still work.
"""

from __future__ import annotations

from pathlib import Path

from agent.graph import _load_sample_data

SAMPLE = Path("sample_data")


def _sample_files() -> list[Path]:
    return sorted(path for path in SAMPLE.rglob("*") if path.is_file())


def test_there_are_sample_files_to_check():
    """Guard against the whole suite passing vacuously if sample_data moves."""
    assert len(_sample_files()) >= 6


def test_every_sample_file_produces_chunks():
    for path in _sample_files():
        chunks = _load_sample_data([str(path)])
        assert chunks, f"{path.relative_to(SAMPLE)} produced no chunks"


# Directories that intentionally carry no data. Listing them explicitly keeps the test above
# honest: a fixture that silently empties out is a failure, not a quieter version of passing.
EMPTY_FIXTURE_DIRS = {"monitor_price_drop_case"}


def test_every_sample_directory_produces_chunks():
    for directory in sorted(p for p in SAMPLE.iterdir() if p.is_dir()):
        chunks = _load_sample_data([str(directory)])
        if directory.name in EMPTY_FIXTURE_DIRS:
            assert not chunks, f"{directory.name}/ is listed as empty but produced chunks"
            continue
        assert chunks, f"{directory.name}/ produced no chunks"


def test_html_policy_page_contributes_its_labels():
    """The html page must not merely exist -- its structure has to survive ingestion."""
    path = SAMPLE / "laptop_return_case" / "return_policy.html"
    chunks = _load_sample_data([str(path)])
    labels: dict[str, str] = {}
    for chunk in chunks:
        labels.update(chunk.metadata.get("labels") or {})
    assert labels.get("return window", "").startswith("14 days"), labels
    assert "exclusions" in labels, labels


def test_text_warranty_card_contributes_its_labels():
    path = SAMPLE / "headphone_warranty_case" / "warranty_card.txt"
    chunks = _load_sample_data([str(path)])
    labels: dict[str, str] = {}
    for chunk in chunks:
        labels.update(chunk.metadata.get("labels") or {})
    assert "warranty period" in labels, labels
    assert "return policy" in labels, labels
