"""doc_type inference: filename and content, in one place.

`doc_type` decides whether a document is even read: `policy_agent` only looks at chunks
whose doc_type is in `{warranty, policy, receipt}`.  Inference used to be duplicated per
parser and, for ``.txt``, based on the filename alone — so ``return_policy.txt`` became
``manual`` and the return policy was silently ignored.  Nothing failed; the answer was just
missing a document.

The contract tested here:

* a filename keyword wins over the extension default;
* content keywords are consulted when the filename says nothing;
* ``.txt`` no longer defaults to ``manual``;
* an unrecognised document still ends up ``manual`` rather than being guessed into a
  category that changes how it is read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.graph import _load_sample_data
from ingestion.doc_type import infer_doc_type

POLICY_BODY = (
    "Return Window: 14 days from delivery\n"
    "Condition: unused and in original packaging\n"
    "Refund: full refund to original payment method\n"
)
WARRANTY_BODY = (
    "Limited Warranty\n"
    "Warranty Period: 1 year from the date of purchase\n"
    "Coverage: defects in materials and workmanship\n"
)
RECEIPT_BODY = "Total: $1,299.00\nDate: 2026-05-15\nOrder #: ORD-1\n"
MANUAL_BODY = "Step 1: plug the device in.\nStep 2: hold the power button.\n"


@pytest.mark.parametrize(
    "filename,expected",
    [
        # policy, stated in the name
        ("return_policy.txt", "policy"),
        ("refund_policy.txt", "policy"),
        ("store_policy.txt", "policy"),
        ("returns.txt", "policy"),
        ("policy.txt", "policy"),
        # warranty, stated in the name
        ("warranty_terms.txt", "warranty"),
        ("warranty_policy.txt", "warranty"),
        ("warranty.txt", "warranty"),
        # receipt, stated in the name
        ("receipt.txt", "receipt"),
        ("invoice.txt", "receipt"),
    ],
)
def test_filename_keywords_decide_the_type(tmp_path: Path, filename: str, expected: str) -> None:
    """The body is deliberately empty: only the filename may be responsible here."""
    path = tmp_path / filename
    path.write_text("")
    assert infer_doc_type(path, "") == expected


@pytest.mark.parametrize("filename", ["manual.txt", "guide.txt", "readme.txt"])
def test_manual_stays_manual(tmp_path: Path, filename: str) -> None:
    path = tmp_path / filename
    path.write_text(MANUAL_BODY)
    assert infer_doc_type(path, MANUAL_BODY) == "manual"


@pytest.mark.parametrize(
    "body",
    [
        "Return Window: 14 days from delivery",
        "Refund Policy: full refund within 30 days",
        "This item is final sale",
        "All sales are final",
    ],
)
def test_policy_content_wins_when_the_name_says_nothing(
    tmp_path: Path, body: str
) -> None:
    path = tmp_path / "unknown.txt"
    path.write_text(body)
    assert infer_doc_type(path, body) == "policy", body


@pytest.mark.parametrize(
    "body",
    [
        "Limited warranty for one year",
        "Warranty Period: 24 months",
        "This device carries a manufacturer warranty",
    ],
)
def test_warranty_content_wins_when_the_name_says_nothing(
    tmp_path: Path, body: str
) -> None:
    path = tmp_path / "unknown.txt"
    path.write_text(body)
    assert infer_doc_type(path, body) == "warranty", body


@pytest.mark.parametrize(
    "body",
    ["Step 1: plug it in", "Operating instructions", "Chapter 3 - Troubleshooting"],
)
def test_unrecognised_content_is_manual_not_guessed(tmp_path: Path, body: str) -> None:
    path = tmp_path / "notes.txt"
    path.write_text(body)
    assert infer_doc_type(path, body) == "manual", body


def test_a_txt_policy_is_never_manual(tmp_path: Path) -> None:
    """The exact regression: a plain-text return policy was classified as a manual."""
    path = tmp_path / "return_policy.txt"
    path.write_text(POLICY_BODY)
    assert infer_doc_type(path, POLICY_BODY) != "manual"


class TestTheNameBeatsTheContent:
    def test_warranty_named_file_is_not_turned_into_a_policy_by_its_body(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "warranty_terms.txt"
        path.write_text(WARRANTY_BODY + "Return Window: 14 days\n")
        assert infer_doc_type(path, path.read_text()) == "warranty"

    def test_receipt_named_file_is_not_turned_into_a_policy_by_its_body(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "receipt.txt"
        path.write_text(RECEIPT_BODY + "Return Window: 30 days\n")
        assert infer_doc_type(path, path.read_text()) == "receipt"


class TestTheFilenameStageDoesNotHijackTheContentStage:
    """A filename keyword must not send a document to a type nothing reads.

    Found while wiring this module up: listing the csv keywords (bank/transaction/price/
    history) globally made ``purchase_history.txt`` and ``price_list.pdf`` resolve to
    ``bank_csv``. Because the filename stage short-circuits the content stage, the policy
    inside such a file was never examined — the same silent drop this module exists to stop.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "purchase_history.txt",
            "price_list.txt",
            "bank_notes.txt",
            "transaction_log.txt",
        ],
    )
    def test_a_bankish_name_does_not_swallow_a_policy(self, tmp_path: Path, filename: str) -> None:
        body = "Return Window: 14 days from delivery\nRefund: full refund within 14 days\n"
        path = tmp_path / filename
        path.write_text(body)
        assert infer_doc_type(path, body) == "policy", (
            f"{filename} was classified away from the content it plainly contains"
        )

    @pytest.mark.parametrize(
        "filename", ["price_list.pdf", "transaction_summary.pdf", "bank_notes.txt"]
    )
    def test_a_non_csv_never_becomes_bank_csv(self, tmp_path: Path, filename: str) -> None:
        path = tmp_path / filename
        path.write_text("nothing in particular")
        assert infer_doc_type(path, "nothing in particular") != "bank_csv"

    def test_a_csv_still_resolves_to_bank_csv(self, tmp_path: Path) -> None:
        path = tmp_path / "purchase_history.csv"
        body = "date,description,amount\n2026-05-15,TECHWORLD,-1299.00\n"
        path.write_text(body)
        assert infer_doc_type(path, body) == "bank_csv"

    def test_a_reviews_csv_is_still_reviews(self, tmp_path: Path) -> None:
        path = tmp_path / "product_reviews.csv"
        body = "rating,text\n5,great laptop\n"
        path.write_text(body)
        assert infer_doc_type(path, body) == "reviews"


class TestIngestionUsesTheInference:
    """`_load_sample_data` must route .txt through the shared function, not its own rules."""

    @pytest.mark.parametrize(
        "filename,body,expected",
        [
            ("return_policy.txt", POLICY_BODY, "policy"),
            ("refund_policy.txt", POLICY_BODY, "policy"),
            ("warranty_terms.txt", WARRANTY_BODY, "warranty"),
            ("receipt.txt", RECEIPT_BODY, "receipt"),
            ("manual.txt", MANUAL_BODY, "manual"),
            ("unknown.txt", "Refund Policy: full refund within 30 days", "policy"),
        ],
    )
    def test_txt_doc_type_after_ingestion(
        self, tmp_path: Path, filename: str, body: str, expected: str
    ) -> None:
        target = tmp_path / "case"
        target.mkdir()
        (target / filename).write_text(body)
        chunks = _load_sample_data([str(target)])
        assert chunks, f"{filename} produced no chunks"
        assert {c.metadata.get("doc_type") for c in chunks} == {expected}

    def test_a_txt_policy_is_readable_by_the_policy_agent(self, tmp_path: Path) -> None:
        """The end the inference exists for: the chunk must be in the readable set."""
        target = tmp_path / "policy_only"
        target.mkdir()
        (target / "return_policy.txt").write_text(POLICY_BODY)
        chunks = _load_sample_data([str(target)])
        readable = {"warranty", "policy", "receipt"}
        assert {c.metadata.get("doc_type") for c in chunks} <= readable, (
            "a plain-text policy is not in the set policy_agent reads"
        )
