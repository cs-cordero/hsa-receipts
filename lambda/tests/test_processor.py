"""Tests for archiver.processor module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from hsa_receipt_archiver.archiver.processor import process_attachment
from hsa_receipt_archiver.claude_client import EligibilityResult


def _make_eligibility_result(**overrides: object) -> EligibilityResult:
    defaults: dict[str, object] = {
        "is_eligible": True,
        "description": "Office visit",
        "short_description": "Medical",
        "category": "Medical",
        "amount": 100.0,
        "provider": "Dr Smith",
        "service_date": "2025-02-15",
        "payment_date": None,
        "patient": "CHRIS",
        "reasoning": "Eligible",
    }
    defaults.update(overrides)
    return EligibilityResult(**defaults)  # type: ignore[arg-type]


class TestProcessAttachment:
    @patch("hsa_receipt_archiver.archiver.processor.store_ledger")
    @patch("hsa_receipt_archiver.archiver.processor.fetch_ledger", return_value=None)
    @patch("hsa_receipt_archiver.archiver.processor.store_receipt", return_value="s3://b/r.pdf")
    @patch("hsa_receipt_archiver.archiver.processor.convert_to_pdfa", return_value=b"pdf-data")
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_eligible_receipt_creates_entry(
        self,
        mock_check: MagicMock,
        mock_convert: MagicMock,
        mock_store_receipt: MagicMock,
        mock_fetch_ledger: MagicMock,
        mock_store_ledger: MagicMock,
    ) -> None:
        mock_check.return_value = [_make_eligibility_result()]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket")

        assert len(result.entries) == 1
        assert result.entries[0].provider == "Dr Smith"
        assert result.entries[0].amount == 100.0
        assert result.receipt_s3_uri == "s3://b/r.pdf"
        assert len(result.rejections) == 0
        mock_convert.assert_called_once()
        mock_store_receipt.assert_called_once()
        mock_store_ledger.assert_called_once()

    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_ineligible_receipt_returns_rejection(self, mock_check: MagicMock) -> None:
        mock_check.return_value = [_make_eligibility_result(is_eligible=False)]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket")

        assert len(result.entries) == 0
        assert len(result.rejections) == 1
        assert result.rejections[0].filename == "receipt.jpg"
        assert result.receipt_s3_uri is None

    @patch("hsa_receipt_archiver.archiver.processor.store_ledger")
    @patch("hsa_receipt_archiver.archiver.processor.fetch_ledger", return_value=None)
    @patch("hsa_receipt_archiver.archiver.processor.store_receipt", return_value="s3://b/r.pdf")
    @patch("hsa_receipt_archiver.archiver.processor.convert_to_pdfa", return_value=b"pdf")
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_force_store_bypasses_eligibility(
        self,
        mock_check: MagicMock,
        mock_convert: MagicMock,
        mock_store_receipt: MagicMock,
        mock_fetch_ledger: MagicMock,
        mock_store_ledger: MagicMock,
    ) -> None:
        mock_check.return_value = [_make_eligibility_result(is_eligible=False)]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", True, "key", "bucket")

        assert len(result.entries) == 1
        assert len(result.rejections) == 0
        mock_store_receipt.assert_called_once()

    @patch("hsa_receipt_archiver.archiver.processor.store_ledger")
    @patch("hsa_receipt_archiver.archiver.processor.fetch_ledger", return_value=None)
    @patch("hsa_receipt_archiver.archiver.processor.store_receipt", return_value="s3://b/r.pdf")
    @patch("hsa_receipt_archiver.archiver.processor.convert_to_pdfa", return_value=b"pdf")
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_multiple_results_share_receipt_uri(
        self,
        mock_check: MagicMock,
        mock_convert: MagicMock,
        mock_store_receipt: MagicMock,
        mock_fetch_ledger: MagicMock,
        mock_store_ledger: MagicMock,
    ) -> None:
        mock_check.return_value = [
            _make_eligibility_result(description="Visit 1"),
            _make_eligibility_result(description="Visit 2"),
        ]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket")

        assert len(result.entries) == 2
        mock_store_receipt.assert_called_once()
        assert mock_store_ledger.call_count == 2

    @patch("hsa_receipt_archiver.archiver.processor.store_ledger")
    @patch("hsa_receipt_archiver.archiver.processor.fetch_ledger", return_value=None)
    @patch("hsa_receipt_archiver.archiver.processor.store_receipt", return_value="s3://b/r.pdf")
    @patch("hsa_receipt_archiver.archiver.processor.convert_to_pdfa", return_value=b"pdf")
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_both_dates_none_uses_today(
        self,
        mock_check: MagicMock,
        mock_convert: MagicMock,
        mock_store_receipt: MagicMock,
        mock_fetch_ledger: MagicMock,
        mock_store_ledger: MagicMock,
    ) -> None:
        mock_check.return_value = [_make_eligibility_result(service_date=None, payment_date=None)]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", True, "key", "bucket")

        assert len(result.entries) == 1
        assert result.entries[0].payment_date == datetime.now(tz=UTC).date()

    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_too_many_transactions_raises(self, mock_check: MagicMock) -> None:
        mock_check.return_value = [_make_eligibility_result(description=f"Tx {i}") for i in range(4)]

        with pytest.raises(ValueError, match="Manual entry"):
            process_attachment(b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket")

    @patch("hsa_receipt_archiver.archiver.processor.get_page_count", return_value=15)
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_pdf_too_many_pages_raises(self, mock_check: MagicMock, mock_pages: MagicMock) -> None:
        with pytest.raises(ValueError, match="15 pages"):
            process_attachment(b"data", "application/pdf", "big.pdf", False, "key", "bucket")

    @patch("hsa_receipt_archiver.archiver.processor.store_ledger")
    @patch("hsa_receipt_archiver.archiver.processor.fetch_ledger", return_value=None)
    @patch("hsa_receipt_archiver.archiver.processor.store_receipt", return_value="s3://b/r.pdf")
    @patch("hsa_receipt_archiver.archiver.processor.convert_to_pdfa", return_value=b"pdf")
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_invalid_patient_defaults_to_unknown(
        self,
        mock_check: MagicMock,
        mock_convert: MagicMock,
        mock_store_receipt: MagicMock,
        mock_fetch_ledger: MagicMock,
        mock_store_ledger: MagicMock,
    ) -> None:
        mock_check.return_value = [_make_eligibility_result(patient="John Doe")]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket")

        assert result.entries[0].patient == "UNKNOWN"

    @patch("hsa_receipt_archiver.archiver.processor.store_ledger")
    @patch("hsa_receipt_archiver.archiver.processor.fetch_ledger", return_value=None)
    @patch("hsa_receipt_archiver.archiver.processor.store_receipt", return_value="s3://b/r.pdf")
    @patch("hsa_receipt_archiver.archiver.processor.convert_to_pdfa", return_value=b"pdf")
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_none_patient_defaults_to_unknown(
        self,
        mock_check: MagicMock,
        mock_convert: MagicMock,
        mock_store_receipt: MagicMock,
        mock_fetch_ledger: MagicMock,
        mock_store_ledger: MagicMock,
    ) -> None:
        mock_check.return_value = [_make_eligibility_result(patient=None)]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket")

        assert result.entries[0].patient == "UNKNOWN"

    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_receipt_before_earliest_date_rejected(self, mock_check: MagicMock) -> None:
        mock_check.return_value = [_make_eligibility_result(service_date="2025-01-10")]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket")

        assert len(result.entries) == 0
        assert len(result.rejections) == 1
        assert "predates the HSA account" in result.rejections[0].reasoning
        assert result.receipt_s3_uri is None

    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_force_store_does_not_bypass_date_check(self, mock_check: MagicMock) -> None:
        mock_check.return_value = [_make_eligibility_result(service_date="2025-01-10")]

        result = process_attachment(b"data", "image/jpeg", "receipt.jpg", True, "key", "bucket")

        assert len(result.entries) == 0
        assert len(result.rejections) == 1
        assert "predates the HSA account" in result.rejections[0].reasoning

    @patch("hsa_receipt_archiver.archiver.processor.store_receipt", return_value="s3://b/manual.pdf")
    @patch("hsa_receipt_archiver.archiver.processor.convert_to_pdfa", return_value=b"pdf")
    @patch("hsa_receipt_archiver.archiver.processor.check_hsa_eligibility")
    def test_store_only_skips_analysis_and_ledger(
        self,
        mock_check: MagicMock,
        mock_convert: MagicMock,
        mock_store_receipt: MagicMock,
    ) -> None:
        result = process_attachment(
            b"data", "image/jpeg", "receipt.jpg", False, "key", "bucket", store_only=True
        )

        assert len(result.entries) == 0
        assert len(result.rejections) == 0
        assert result.receipt_s3_uri == "s3://b/manual.pdf"
        mock_check.assert_not_called()
        mock_convert.assert_called_once()
        mock_store_receipt.assert_called_once()
