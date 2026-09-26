"""``/api/chat`` must not read arbitrary paths off the filesystem.

``ChatRequest.source_dirs`` was passed straight into ``run_workflow`` and from there into
``Path(sid).resolve()`` + ``iterdir()``+``read_bytes()``.  Any caller could therefore ask
the service to parse ``/tmp/loopcase`` — or ``/etc``, or a home directory — and have the
contents flow back out through the answer.  That is a local file disclosure primitive, not
a feature.

Only paths under the configured ``SAFE_SOURCE_ROOTS`` may be read.  Everything else is
refused *before* the workflow is entered, so a rejected request costs no ingestion work and
leaks nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import apps.api.main as api

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA = ROOT / "sample_data"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(api.app)


@pytest.fixture()
def workflow_spy(monkeypatch):
    """Record every call that reaches the workflow."""
    calls: list[tuple] = []

    def spy(user_query, uploaded_source_ids=None, user_id="default"):
        calls.append((user_query, tuple(uploaded_source_ids or ())))
        return {"final_answer": {"status": "complete", "summary": "spy"}, "intent": "x"}

    monkeypatch.setattr(api, "run_workflow", spy)
    return calls


class TestRejectedPaths:
    @pytest.mark.parametrize(
        "source_dir",
        [
            "/tmp/loopcase",
            "/etc",
            "/",
            str(Path.home()),
            str(ROOT / "agent"),
        ],
        ids=["tmp_loopcase", "etc", "root", "home", "project_source"],
    )
    def test_out_of_scope_absolute_path_is_refused(
        self, client: TestClient, workflow_spy, source_dir: str
    ) -> None:
        response = client.post("/api/chat", json={"query": "hi", "source_dirs": [source_dir]})
        assert response.status_code in (400, 403), (
            f"{source_dir!r} returned {response.status_code}; absolute paths outside the "
            "allowed roots must be refused"
        )

    def test_traversal_escape_is_refused(self, client: TestClient, workflow_spy) -> None:
        escape = str(SAMPLE_DATA / ".." / ".." / ".." / "etc")
        response = client.post("/api/chat", json={"query": "hi", "source_dirs": [escape]})
        assert response.status_code in (400, 403), (
            f"traversal escape returned {response.status_code}"
        )

    def test_symlink_out_of_scope_is_refused(
        self, client: TestClient, workflow_spy, tmp_path: Path
    ) -> None:
        link = SAMPLE_DATA / "_tmp_escape_link"
        try:
            link.symlink_to("/etc")
        except OSError:  # pragma: no cover - filesystem without symlink support
            pytest.skip("symlinks unavailable")
        try:
            response = client.post("/api/chat", json={"query": "hi", "source_dirs": [str(link)]})
            assert response.status_code in (400, 403)
        finally:
            link.unlink(missing_ok=True)

    def test_rejected_request_never_enters_the_workflow(
        self, client: TestClient, workflow_spy
    ) -> None:
        client.post("/api/chat", json={"query": "hi", "source_dirs": ["/tmp/loopcase"]})
        assert workflow_spy == [], (
            "a rejected path still reached run_workflow; the check has to happen before the "
            f"workflow is entered (calls: {workflow_spy})"
        )


class TestAllowedPaths:
    def test_relative_sample_data_path_is_allowed(
        self, client: TestClient, workflow_spy
    ) -> None:
        response = client.post(
            "/api/chat",
            json={"query": "hi", "source_dirs": ["sample_data/laptop_return_case"]},
        )
        assert response.status_code == 200, response.text
        assert len(workflow_spy) == 1

    def test_absolute_path_inside_sample_data_is_allowed(
        self, client: TestClient, workflow_spy
    ) -> None:
        response = client.post(
            "/api/chat",
            json={"query": "hi", "source_dirs": [str(SAMPLE_DATA / "headphone_warranty_case")]},
        )
        assert response.status_code == 200, response.text

    def test_default_source_dirs_are_allowed(self, client: TestClient, workflow_spy) -> None:
        response = client.post("/api/chat", json={"query": "hi"})
        assert response.status_code == 200, response.text

    def test_sample_data_root_itself_is_allowed(self, client: TestClient, workflow_spy) -> None:
        response = client.post(
            "/api/chat", json={"query": "hi", "source_dirs": ["sample_data"]}
        )
        assert response.status_code == 200, response.text


class TestAllowedRootsAreDeclared:
    def test_safe_source_roots_is_configured(self) -> None:
        declared = getattr(api, "SAFE_SOURCE_ROOTS", None)
        assert declared is not None, (
            "the allowed roots must be an explicit, inspectable setting (SAFE_SOURCE_ROOTS)"
        )
        roots = [Path(r).resolve() for r in declared]
        assert roots, "SAFE_SOURCE_ROOTS is empty, which would allow nothing at all"
        assert any(
            r == SAMPLE_DATA.resolve() or SAMPLE_DATA.resolve().is_relative_to(r) for r in roots
        ), f"sample_data is not covered by SAFE_SOURCE_ROOTS={roots}"


class TestHealthEndpoint:
    def test_health_is_unaffected(self, client: TestClient) -> None:
        assert client.get("/health").json()["status"] == "ok"
