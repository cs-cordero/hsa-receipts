"""Tests for email_sender module."""

from unittest.mock import MagicMock, patch

from hsa_receipt_archiver.email_sender import send_confirmation, send_error_notice, send_rejection_notice
from hsa_receipt_archiver.ledger_manager import LedgerEntry


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_confirmation_calls_ses(mock_ses: MagicMock, sample_ledger_entry: LedgerEntry) -> None:
    send_confirmation("from@example.com", "to@example.com", sample_ledger_entry)
    mock_ses.send_email.assert_called_once()
    call_kwargs = mock_ses.send_email.call_args[1]
    assert call_kwargs["Source"] == "from@example.com"
    assert call_kwargs["Destination"] == {"ToAddresses": ["to@example.com"]}


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_confirmation_body_includes_entry_details(mock_ses: MagicMock, sample_ledger_entry: LedgerEntry) -> None:
    send_confirmation("from@example.com", "to@example.com", sample_ledger_entry)
    body = mock_ses.send_email.call_args[1]["Message"]["Body"]["Text"]["Data"]
    assert "Test Provider" in body
    assert "$123.45" in body
    assert "2025-01-15" in body
    assert "2025-01-16" in body
    assert "Medical" in body
    assert "Office visit copay" in body


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_confirmation_none_dates_show_na(mock_ses: MagicMock) -> None:
    entry = LedgerEntry(
        service_date=None,
        payment_date=None,
        provider="P",
        category="Other",
        description="D",
        amount=10.00,
        receipt_s3_uri="s3://b/r.pdf",
    )
    send_confirmation("from@example.com", "to@example.com", entry)
    body = mock_ses.send_email.call_args[1]["Message"]["Body"]["Text"]["Data"]
    assert "N/A" in body


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_confirmation_subject_includes_description(mock_ses: MagicMock, sample_ledger_entry: LedgerEntry) -> None:
    send_confirmation("from@example.com", "to@example.com", sample_ledger_entry)
    subject = mock_ses.send_email.call_args[1]["Message"]["Subject"]["Data"]
    assert "Office visit copay" in subject


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_rejection_notice_calls_ses(mock_ses: MagicMock) -> None:
    send_rejection_notice("from@example.com", "to@example.com", "Gym membership", "Not HSA-eligible")
    mock_ses.send_email.assert_called_once()


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_rejection_notice_includes_reasoning(mock_ses: MagicMock) -> None:
    send_rejection_notice("from@example.com", "to@example.com", "Gym membership", "Not HSA-eligible")
    body = mock_ses.send_email.call_args[1]["Message"]["Body"]["Text"]["Data"]
    assert "Not HSA-eligible" in body
    assert "Gym membership" in body


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_rejection_notice_includes_force_store_instructions(mock_ses: MagicMock) -> None:
    send_rejection_notice("from@example.com", "to@example.com", "Item", "Reason")
    body = mock_ses.send_email.call_args[1]["Message"]["Body"]["Text"]["Data"]
    assert "FORCE_STORE" in body


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_error_notice_calls_ses(mock_ses: MagicMock) -> None:
    send_error_notice("from@example.com", "to@example.com", "Something broke")
    mock_ses.send_email.assert_called_once()
    call_kwargs = mock_ses.send_email.call_args[1]
    assert call_kwargs["Source"] == "from@example.com"
    assert call_kwargs["Destination"] == {"ToAddresses": ["to@example.com"]}


@patch("hsa_receipt_archiver.email_sender.SES_CLIENT")
def test_send_error_notice_includes_error_message(mock_ses: MagicMock) -> None:
    send_error_notice("from@example.com", "to@example.com", "Failed to process attachment: receipt.pdf")
    body = mock_ses.send_email.call_args[1]["Message"]["Body"]["Text"]["Data"]
    assert "Failed to process attachment: receipt.pdf" in body
