"""Upload handling for the Streamlit UI.

The UI is the first component that takes file names from a *user* and hands them to the
workflow, so the path rules matter more here than anywhere else in the project: a name
arriving from a browser is untrusted input, not a path.

Two properties are asserted that a helper-only test would miss:

* a session directory must satisfy the **same** whitelist the HTTP API enforces — the UI
  writes the directory, so if it ever wrote outside `SAFE_SOURCE_ROOTS` the analysis call
  would be refused and the UI would be broken rather than dangerous, and the test would say
  so;
* the sample-case shortcuts must point at directories that actually exist and carry
  documents, otherwise the button is a promise the repository does not keep.

No `streamlit` import: the helpers are plain functions, so these tests run on any install
and cannot turn into a silent module-level skip.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from apps.api.main import resolve_source_dirs
from apps.safe_paths import SAFE_SOURCE_ROOTS, UPLOAD_ROOT, is_within_safe_roots
from apps.ui.uploads import (
    ALLOWED_UPLOAD_EXTENSIONS,
    SAMPLE_CASES,
    UnsafeUploadError,
    analyze,
    new_session_dir,
    safe_upload_target,
    sample_case_path,
    save_uploads,
)

RECEIPT = (
    "TECHWORLD INC. - SALES RECEIPT\n"
    "Date: 2026-05-15 16:20:00\n"
    "Total: $1,299.00\n\n"
    "Return Policy: 30 days from purchase date\n"
)
POLICY = "Return Window: 14 days from delivery\nRefund: full refund to the payment method\n"


@pytest.fixture()
def session_dir():
    """A real session directory under data/uploads, removed afterwards."""
    path = new_session_dir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestSessionDirectory:
    def test_a_session_directory_is_created_under_the_upload_root(self) -> None:
        path = new_session_dir()
        try:
            assert path.is_dir()
            assert path.parent == UPLOAD_ROOT.resolve()
            assert path.name.startswith("session_")
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def test_concurrent_sessions_do_not_collide(self) -> None:
        first, second = new_session_dir(), new_session_dir()
        try:
            assert first != second
        finally:
            shutil.rmtree(first, ignore_errors=True)
            shutil.rmtree(second, ignore_errors=True)

    def test_the_upload_root_is_a_safe_source_root(self) -> None:
        """Requirement: whatever the UI writes must be readable by the workflow."""
        assert UPLOAD_ROOT.resolve() in {root.resolve() for root in SAFE_SOURCE_ROOTS}

    def test_a_session_directory_passes_the_api_whitelist(self, session_dir: Path) -> None:
        """The exact check the HTTP endpoint performs, applied to the UI's own directory."""
        assert resolve_source_dirs([str(session_dir)]) == [str(session_dir.resolve())]

    def test_a_session_directory_is_within_the_safe_roots(self, session_dir: Path) -> None:
        assert is_within_safe_roots(session_dir)


class TestUploadTargets:
    def test_a_plain_name_resolves_inside_the_session(self, session_dir: Path) -> None:
        target = safe_upload_target(session_dir, "receipt.txt")
        assert target == session_dir / "receipt.txt"
        assert target.parent == session_dir

    @pytest.mark.parametrize(
        "filename",
        [
            "../escape.txt",
            "../../escape.txt",
            "sub/../../escape.txt",
            "sub/receipt.txt",
            "/etc/passwd.txt",
            "/tmp/receipt.txt",
            "..",
            ".",
            "",
        ],
    )
    def test_path_components_are_refused(self, session_dir: Path, filename: str) -> None:
        with pytest.raises(UnsafeUploadError):
            safe_upload_target(session_dir, filename)

    @pytest.mark.parametrize(
        "filename",
        ["receipt.exe", "receipt", "receipt.txt.bak", ".env", "payload.sh", "notes.docx"],
    )
    def test_disallowed_extensions_are_refused(self, session_dir: Path, filename: str) -> None:
        with pytest.raises(UnsafeUploadError):
            safe_upload_target(session_dir, filename)

    @pytest.mark.parametrize(
        "filename",
        ["receipt.txt", "Warranty.PDF", "return_policy.HTML", "bank.csv", "support.eml"],
    )
    def test_every_documented_extension_is_accepted(
        self, session_dir: Path, filename: str
    ) -> None:
        assert safe_upload_target(session_dir, filename).name == filename

    def test_the_documented_extension_set_is_exactly_what_the_ui_offers(self) -> None:
        assert ALLOWED_UPLOAD_EXTENSIONS == {".txt", ".pdf", ".csv", ".eml", ".html"}

    def test_a_symlink_cannot_be_used_to_escape_the_session(self, session_dir: Path) -> None:
        """A name that resolves outside the session is refused, symlink or not."""
        outside = session_dir.parent / "outside_target.txt"
        outside.write_text("outside the session")
        link = session_dir / "link.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks unavailable")
        try:
            with pytest.raises(UnsafeUploadError):
                safe_upload_target(session_dir, "link.txt")
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)


class TestSaveUploads:
    def test_files_are_written_inside_the_session(self, session_dir: Path) -> None:
        written = save_uploads(
            session_dir, [("receipt.txt", RECEIPT.encode()), ("return_policy.txt", POLICY.encode())]
        )
        assert [p.name for p in written] == ["receipt.txt", "return_policy.txt"]
        for path in written:
            assert path.parent == session_dir
            assert path.read_bytes()

    def test_a_bad_name_aborts_the_whole_upload(self, session_dir: Path) -> None:
        """Partial writes would leave a directory that looks usable but is not the user's."""
        with pytest.raises(UnsafeUploadError):
            save_uploads(
                session_dir,
                [("receipt.txt", RECEIPT.encode()), ("../escape.txt", b"nope")],
            )
        assert not (session_dir / "receipt.txt").exists()

    def test_an_empty_upload_list_writes_nothing(self, session_dir: Path) -> None:
        assert save_uploads(session_dir, []) == []
        assert list(session_dir.iterdir()) == []


class TestSampleCases:
    def test_the_two_documented_shortcuts_exist(self) -> None:
        assert set(SAMPLE_CASES) == {"headphone", "laptop"}

    @pytest.mark.parametrize("name", sorted(SAMPLE_CASES))
    def test_each_shortcut_directory_exists_and_carries_documents(self, name: str) -> None:
        path = sample_case_path(name)
        assert path.is_dir()
        documents = [p for p in path.iterdir() if p.is_file()]
        assert documents, f"{name} has no documents, so the button would load nothing"

    def test_each_shortcut_passes_the_api_whitelist(self) -> None:
        for name in SAMPLE_CASES:
            assert resolve_source_dirs([str(sample_case_path(name))])

    def test_an_unknown_shortcut_is_refused(self) -> None:
        with pytest.raises(UnsafeUploadError):
            sample_case_path("../../etc")

    def test_a_sample_path_is_never_built_from_user_text(self) -> None:
        """The lookup is a fixed table, so a traversal string can only ever miss."""
        with pytest.raises(UnsafeUploadError):
            sample_case_path("headphone_warranty_case")


class TestAnalyze:
    def test_analyze_returns_a_workflow_result(self, session_dir: Path) -> None:
        save_uploads(
            session_dir,
            [
                ("receipt.txt", RECEIPT.encode()),
                ("return_policy.txt", POLICY.encode()),
            ],
        )
        result = analyze("Can I return this laptop I bought last week?", session_dir)
        answer = result.get("final_answer") or {}
        assert answer.get("status"), "analyze must return a workflow result with a status"
        assert "retrieved_evidence" in result

    def test_analyze_refuses_a_directory_outside_the_safe_roots(self, tmp_path: Path) -> None:
        (tmp_path / "receipt.txt").write_text(RECEIPT)
        with pytest.raises(UnsafeUploadError):
            analyze("Can I return this?", tmp_path)

    def test_analyze_output_carries_what_the_page_displays(self, session_dir: Path) -> None:
        save_uploads(session_dir, [("receipt.txt", RECEIPT.encode())])
        result = analyze("Can I return this laptop?", session_dir)
        answer = result.get("final_answer") or {}
        for field in ("status", "summary", "key_facts", "actions", "overall_confidence"):
            assert field in answer, f"the page needs {field!r} and it is missing"
        assert "verified_claims" in result
        assert "unsupported_claims" in result
