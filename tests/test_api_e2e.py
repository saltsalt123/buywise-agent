"""End-to-end tests through the HTTP surface.

These go through ``TestClient`` rather than calling ``run_workflow`` directly, so the
request model, the path whitelist, the response model and the status handling are all
exercised the way a caller hits them.  A unit test on the workflow cannot catch a response
model that silently drops a field or an endpoint that stamps its own status over the
answer's.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import apps.api.main as api
from tests.case_fixtures import contradictory_case

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data"

HEADPHONE = "sample_data/headphone_warranty_case"
LAPTOP = "sample_data/laptop_return_case"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(api.app)


def _post(client: TestClient, query: str, source_dirs):
    payload = {"query": query}
    if source_dirs is not None:
        payload["source_dirs"] = source_dirs
    return client.post("/api/chat", json=payload)


class TestHappyPaths:
    def test_headphone_case_returns_complete(self, client: TestClient) -> None:
        r = _post(client, "My headphones stopped charging after 7 months. "
                          "Can I claim warranty?", [HEADPHONE])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "complete"
        assert body["intent"] == "warranty_or_return"
        assert body["key_facts"], "a complete analysis must surface key facts"
        assert body["evidence_count"] > 0

    def test_laptop_case_returns_complete(self, client: TestClient) -> None:
        r = _post(client, "Can I return this laptop I bought on May 15?", [LAPTOP])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "complete"
        assert body["intent"] == "warranty_or_return"
        assert body["evidence_count"] > 0

    def test_default_source_dirs_are_used_when_omitted(self, client: TestClient) -> None:
        r = _post(client, "My headphones stopped charging after 7 months. "
                          "Can I claim warranty?", None)
        assert r.status_code == 200, r.text

    def test_response_includes_raw_answer(self, client: TestClient) -> None:
        body = _post(client, "Can I return this laptop I bought on May 15?", [LAPTOP]).json()
        assert body["raw"], "the raw answer should be passed through for inspection"
        assert "status" in body["raw"]


class TestStatusIsNotHardcoded:
    """`status` must come from the run, not from the response layer.

    The no-evidence path is reached through an *allowed* path that resolves to no documents
    (``sample_data/no_such_dir``).  A temporary directory cannot be used: it is outside
    ``SAFE_SOURCE_ROOTS``, so the request is correctly refused with 400 before the workflow
    runs — which is itself covered in ``TestPathWhitelistThroughTheApi``.
    """

    NO_DOCUMENTS = "sample_data/no_such_dir"

    def test_no_documents_reports_missing_evidence(self, client: TestClient) -> None:
        body = _post(client, "Can I return this laptop I bought on May 15?",
                     [self.NO_DOCUMENTS]).json()
        assert body["status"] in {"no_evidence", "insufficient_evidence"}, body["status"]
        assert body["confidence"] == 0.0

    def test_no_documents_drafts_nothing(self, client: TestClient) -> None:
        body = _post(client, "Can I return this laptop I bought on May 15?",
                     [self.NO_DOCUMENTS]).json()
        ids = {a["action_id"] for a in body["actions"]}
        assert "act_return_request" not in ids
        assert "act_warranty_claim" not in ids
        assert ids == {"act_checklist"}

    def test_unsupported_intent_is_reported(self, client: TestClient) -> None:
        body = _post(client, "Which laptop should I buy?", [LAPTOP]).json()
        assert body["status"] == "unsupported_intent"
        assert body["actions"] == []
        assert body["key_facts"] == []

    def test_status_survives_every_supported_outcome(self, client: TestClient) -> None:
        """A no-evidence run and a complete run must not report the same status."""
        complete = _post(client, "Can I return this laptop I bought on May 15?", [LAPTOP]).json()
        empty = _post(client, "Can I return this laptop I bought on May 15?",
                      [self.NO_DOCUMENTS]).json()
        assert complete["status"] == "complete"
        assert complete["status"] != empty["status"], (
            "the endpoint is stamping a fixed status over the workflow's own result"
        )
        assert complete["confidence"] != empty["confidence"]


class TestPathWhitelistThroughTheApi:
    @pytest.mark.parametrize(
        "source_dir", ["/tmp", "/etc", "/tmp/loopcase", str(Path.home())],
        ids=["tmp", "etc", "tmp_loopcase", "home"],
    )
    def test_out_of_scope_paths_are_refused(self, client: TestClient, source_dir: str) -> None:
        r = _post(client, "hi", [source_dir])
        assert r.status_code in (400, 403), f"{source_dir!r} -> {r.status_code}"
        assert "outside the allowed roots" in r.json().get("detail", "")

    def test_refusal_never_reads_the_path(self, client: TestClient, tmp_path: Path) -> None:
        """A refused path must not be opened; the directory is never touched."""
        target = tmp_path / "secret"
        target.mkdir()
        sentinel = target / "secret_receipt.txt"
        sentinel.write_text("Date: 2099-01-01\nReturn Policy: 999 days\n")
        before = sentinel.stat().st_mtime_ns

        r = _post(client, "hi", [str(target)])
        assert r.status_code in (400, 403)
        assert sentinel.read_text() == "Date: 2099-01-01\nReturn Policy: 999 days\n"
        assert sentinel.stat().st_mtime_ns == before

    def test_traversal_and_symlink_escapes_are_refused(self, client: TestClient) -> None:
        traversal = str(SAMPLE / ".." / ".." / ".." / "etc")
        assert _post(client, "hi", [traversal]).status_code in (400, 403)

        link = SAMPLE / "_e2e_escape_link"
        try:
            link.symlink_to("/etc")
        except OSError:
            pytest.skip("symlinks unavailable")
        try:
            assert _post(client, "hi", [str(link)]).status_code in (400, 403)
        finally:
            link.unlink(missing_ok=True)


class TestMissingPathsDoNotCrash:
    def test_nonexistent_path_inside_the_whitelist_is_not_a_500(
        self, client: TestClient
    ) -> None:
        r = _post(client, "Can I return this laptop?", ["sample_data/does_not_exist"])
        assert r.status_code != 500, r.text
        assert r.status_code in (200, 400, 404)
        if r.status_code == 200:
            assert r.json()["status"] in {"no_evidence", "insufficient_evidence"}

    def test_missing_path_outside_the_whitelist_is_refused_not_crashed(
        self, client: TestClient
    ) -> None:
        r = _post(client, "hi", ["/tmp/definitely_not_here"])
        assert r.status_code in (400, 403), r.text

    def test_empty_source_dir_list_does_not_crash(self, client: TestClient) -> None:
        r = _post(client, "Can I return this laptop?", [])
        assert r.status_code != 500, r.text
        assert r.json()["status"] in {"no_evidence", "insufficient_evidence"}

    def test_mixed_valid_and_invalid_paths_is_refused_wholesale(
        self, client: TestClient
    ) -> None:
        """One bad entry must not be silently dropped while the good one is read."""
        r = _post(client, "hi", [LAPTOP, "/etc"])
        assert r.status_code in (400, 403)


class TestHealthAndSchema:
    def test_health_still_works(self, client: TestClient) -> None:
        assert client.get("/health").json()["status"] == "ok"

    def test_response_schema_is_complete(self, client: TestClient) -> None:
        body = _post(client, "Can I return this laptop I bought on May 15?", [LAPTOP]).json()
        for field in ("status", "intent", "summary", "key_facts", "actions",
                      "evidence_count", "confidence", "raw"):
            assert field in body, f"response is missing {field!r}"

    def test_contradictory_fixture_is_refused_because_it_is_outside_the_roots(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """A document set built in a temp dir cannot be read through the API at all.

        The contradictory case is therefore covered at the workflow level
        (``test_golden_outputs.py``) and in the eval, both of which call the workflow
        directly.  Asserted here so the reason is recorded rather than rediscovered.
        """
        src = contradictory_case(tmp_path / "contradictory")
        r = _post(client, "Can I return this laptop I bought last week?", [src])
        assert r.status_code in (400, 403)
        assert "outside the allowed roots" in r.json().get("detail", "")
