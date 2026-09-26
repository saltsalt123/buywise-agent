"""The Streamlit page, executed headlessly.

A 200 from the Streamlit server only proves the static shell was served — the script itself
runs when a browser connects over a websocket, so an exception in the page would never show
up in a curl. `streamlit.testing.v1.AppTest` runs the script for real and reports what it
raised, which is the difference between "the port answers" and "the page works".

These are smoke tests for thin rendering glue: they assert the page runs, reacts to the
sample-case buttons and the Analyze button, and shows the sections a user needs. The path
rules live in `apps/ui/uploads.py` and are tested in `test_ui_uploads.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Hard import, not importorskip: streamlit is declared in the `dev` extra, and a module-level
# importorskip would turn a missing dependency into one silent skip for this whole file — the
# exact failure mode `make test-ci` exists to catch.
from streamlit.testing.v1 import AppTest

from apps.ui.uploads import ALLOWED_UPLOAD_EXTENSIONS

# Absolute: AppTest resolves a relative path against the file that calls from_file(), not the
# working directory.
APP = str(Path(__file__).resolve().parents[1] / "apps" / "ui" / "streamlit_app.py")


@pytest.fixture()
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


class TestThePageLoads:
    def test_the_script_runs_without_raising(self, app: AppTest) -> None:
        assert not app.exception, [str(e) for e in app.exception]

    def test_the_expected_controls_are_present(self, app: AppTest) -> None:
        assert app.title, "the page needs a title"
        assert len(app.text_input) >= 1, "the query input is missing"
        assert len(app.button) >= 3, "expected Analyze, Clear and the two sample buttons"
        labels = " ".join(b.label for b in app.button)
        assert "Analyze" in labels
        assert "sample" in labels.lower()

    def test_the_file_uploader_offers_the_documented_types(self, app: AppTest) -> None:
        uploaders = app.get("file_uploader")
        assert uploaders, "the file uploader is missing"
        uploader = uploaders[0]
        # `.type` is the Streamlit element kind ("file_uploader"); the accepted extensions live
        # in `.allowed_type`, which the generic Block type does not declare. Compared against
        # the helper's own set so the widget cannot drift from what the ingestion layer takes.
        # Streamlit itself expands "html" to {".html", ".htm"}, hence the one allowed extra.
        offered = set(getattr(uploader, "allowed_type"))
        assert offered - {".htm"} == set(ALLOWED_UPLOAD_EXTENSIONS)
        assert getattr(uploader, "accept_multiple_files") is True

    def test_it_says_what_to_do_first(self, app: AppTest) -> None:
        assert any("Analyze" in str(info.value) for info in app.info)


class TestSampleCaseButton:
    def test_loading_the_headphone_sample_produces_an_analysis(self, app: AppTest) -> None:
        button = next(b for b in app.button if "Headphone" in b.label)
        button.click().run()

        assert not app.exception, [str(e) for e in app.exception]
        assert app.session_state["result"], "the sample run produced no result"
        assert "headphone" in app.session_state["origin"]
        assert any("complete" in str(h.value) for h in app.subheader)

    def test_loading_the_laptop_sample_produces_an_analysis(self, app: AppTest) -> None:
        button = next(b for b in app.button if "Laptop" in b.label)
        button.click().run()

        assert not app.exception, [str(e) for e in app.exception]
        assert app.session_state["result"]
        assert "laptop" in app.session_state["origin"]

    def test_a_sample_run_shows_every_section_the_page_promises(self, app: AppTest) -> None:
        next(b for b in app.button if "Headphone" in b.label).click().run()

        headings = " ".join(m.value for m in app.markdown)
        for section in ("Summary", "Key facts", "Verified claims", "Unsupported", "Actions"):
            assert section in headings, f"the {section!r} section is missing"
        assert any("Evidence chunks" in m.value for m in app.markdown)
        assert app.metric, "the confidence metric is missing"


class TestAnalyzeWithoutDocuments:
    def test_pressing_analyze_with_nothing_loaded_warns(self, app: AppTest) -> None:
        next(b for b in app.button if b.label == "Analyze").click().run()

        assert not app.exception, [str(e) for e in app.exception]
        assert app.warning, "analyze with no documents should warn, not fail silently"
        assert app.session_state.get("result") is None


class TestClearSession:
    def test_clearing_removes_the_stored_result(self, app: AppTest) -> None:
        next(b for b in app.button if "Headphone" in b.label).click().run()
        assert app.session_state["result"]

        next(b for b in app.button if b.label == "Clear session").click().run()

        assert not app.exception, [str(e) for e in app.exception]
        assert app.session_state.get("result") is None
        assert app.session_state.get("session_id") is None
