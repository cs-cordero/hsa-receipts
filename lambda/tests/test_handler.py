"""Tests for handler module."""

import os
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from hsa_receipt_archiver.claude_client import EligibilityResult
from hsa_receipt_archiver.email_parser import Attachment, ParsedEmail
from hsa_receipt_archiver.ledger_manager import LedgerEntry

ENV_VARS = {
    "BUCKET_NAME": "test-bucket",
    "DOMAIN_NAME": "example.com",
    "SSM_API_KEY_PARAM": "/test/api-key",
    "SSM_ALLOWED_SENDERS_PARAM": "/test/senders",
}


def _make_ses_event(message_id: str = "msg-123") -> dict:
    return {"Records": [{"ses": {"mail": {"messageId": message_id}}}]}


def _make_eligibility_result(**overrides: object) -> EligibilityResult:
    defaults: dict[str, object] = {
        "is_eligible": True,
        "description": "Office visit",
        "short_description": "Medical",
        "category": "Medical",
        "amount": 100.0,
        "provider": "Dr Smith",
        "service_date": "2025-01-15",
        "payment_date": None,
        "reasoning": "Eligible",
    }
    defaults.update(overrides)
    return EligibilityResult(**defaults)  # type: ignore[arg-type]


def _make_parsed_email(
    sender: str = "allowed@example.com",
    subject: str = "Receipt",
    attachments: list[Attachment] | None = None,
) -> ParsedEmail:
    if attachments is None:
        attachments = [Attachment("receipt.jpg", "image/jpeg", b"jpeg-data")]
    return ParsedEmail(sender=sender, subject=subject, body="", attachments=attachments)


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler.tag_raw_email")
@patch("hsa_receipt_archiver.handler.send_confirmation")
@patch("hsa_receipt_archiver.handler.store_ledger")
@patch("hsa_receipt_archiver.handler.fetch_ledger", return_value=None)
@patch("hsa_receipt_archiver.handler.store_receipt", return_value="s3://test-bucket/receipts/2025/receipt.pdf")
@patch("hsa_receipt_archiver.handler.convert_to_pdfa", return_value=b"pdf-data")
@patch("hsa_receipt_archiver.handler.check_hsa_eligibility")
@patch("hsa_receipt_archiver.handler.parse_ses_email")
@patch("hsa_receipt_archiver.handler.fetch_raw_email", return_value=b"raw-email")
@patch("hsa_receipt_archiver.handler._get_ssm_param")
def test_happy_path(
    mock_ssm: MagicMock,
    mock_fetch_email: MagicMock,
    mock_parse: MagicMock,
    mock_check: MagicMock,
    mock_convert: MagicMock,
    mock_store_receipt: MagicMock,
    mock_fetch_ledger: MagicMock,
    mock_store_ledger: MagicMock,
    mock_send_conf: MagicMock,
    mock_tag: MagicMock,
) -> None:
    mock_ssm.side_effect = lambda name: {"/test/api-key": "key", "/test/senders": "allowed@example.com"}[name]
    mock_parse.return_value = _make_parsed_email()
    mock_check.return_value = [_make_eligibility_result()]

    from hsa_receipt_archiver.handler import _handle

    result = _handle(_make_ses_event())

    assert result["statusCode"] == 200
    mock_fetch_email.assert_called_once()
    mock_convert.assert_called_once()
    mock_store_receipt.assert_called_once()
    mock_store_ledger.assert_called_once()
    mock_send_conf.assert_called_once()
    mock_tag.assert_called_once()


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler._handle", side_effect=RuntimeError("boom"))
def test_process_receipt_catches_exceptions(mock_handle: MagicMock) -> None:
    from hsa_receipt_archiver.handler import process_receipt

    result = process_receipt(_make_ses_event(), None)
    assert result["statusCode"] == 500


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler.tag_raw_email")
@patch("hsa_receipt_archiver.handler.parse_ses_email")
@patch("hsa_receipt_archiver.handler.fetch_raw_email", return_value=b"raw")
@patch("hsa_receipt_archiver.handler._get_ssm_param")
def test_unauthorized_sender_returns_403(
    mock_ssm: MagicMock,
    mock_fetch: MagicMock,
    mock_parse: MagicMock,
    mock_tag: MagicMock,
) -> None:
    mock_ssm.side_effect = lambda name: {"/test/api-key": "key", "/test/senders": "allowed@example.com"}[name]
    mock_parse.return_value = _make_parsed_email(sender="intruder@evil.com")

    from hsa_receipt_archiver.handler import _handle

    result = _handle(_make_ses_event())
    assert result["statusCode"] == 403
    mock_tag.assert_not_called()


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler.tag_raw_email")
@patch("hsa_receipt_archiver.handler.parse_ses_email")
@patch("hsa_receipt_archiver.handler.fetch_raw_email", return_value=b"raw")
@patch("hsa_receipt_archiver.handler._get_ssm_param")
def test_no_attachments_returns_400(
    mock_ssm: MagicMock,
    mock_fetch: MagicMock,
    mock_parse: MagicMock,
    mock_tag: MagicMock,
) -> None:
    mock_ssm.side_effect = lambda name: {"/test/api-key": "key", "/test/senders": "allowed@example.com"}[name]
    mock_parse.return_value = _make_parsed_email(attachments=[])

    from hsa_receipt_archiver.handler import _handle

    result = _handle(_make_ses_event())
    assert result["statusCode"] == 400


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler.tag_raw_email")
@patch("hsa_receipt_archiver.handler.send_rejection_notice")
@patch("hsa_receipt_archiver.handler.check_hsa_eligibility")
@patch("hsa_receipt_archiver.handler.parse_ses_email")
@patch("hsa_receipt_archiver.handler.fetch_raw_email", return_value=b"raw")
@patch("hsa_receipt_archiver.handler._get_ssm_param")
def test_ineligible_sends_rejection(
    mock_ssm: MagicMock,
    mock_fetch: MagicMock,
    mock_parse: MagicMock,
    mock_check: MagicMock,
    mock_reject: MagicMock,
    mock_tag: MagicMock,
) -> None:
    mock_ssm.side_effect = lambda name: {"/test/api-key": "key", "/test/senders": "allowed@example.com"}[name]
    mock_parse.return_value = _make_parsed_email()
    mock_check.return_value = [_make_eligibility_result(is_eligible=False)]

    from hsa_receipt_archiver.handler import _handle

    result = _handle(_make_ses_event())
    assert result["statusCode"] == 200
    mock_reject.assert_called_once()


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler.tag_raw_email")
@patch("hsa_receipt_archiver.handler.send_confirmation")
@patch("hsa_receipt_archiver.handler.store_ledger")
@patch("hsa_receipt_archiver.handler.fetch_ledger", return_value=None)
@patch("hsa_receipt_archiver.handler.store_receipt", return_value="s3://b/r.pdf")
@patch("hsa_receipt_archiver.handler.convert_to_pdfa", return_value=b"pdf")
@patch("hsa_receipt_archiver.handler.check_hsa_eligibility")
@patch("hsa_receipt_archiver.handler.parse_ses_email")
@patch("hsa_receipt_archiver.handler.fetch_raw_email", return_value=b"raw")
@patch("hsa_receipt_archiver.handler._get_ssm_param")
def test_force_store_bypasses_eligibility(
    mock_ssm: MagicMock,
    mock_fetch: MagicMock,
    mock_parse: MagicMock,
    mock_check: MagicMock,
    mock_convert: MagicMock,
    mock_store_receipt: MagicMock,
    mock_fetch_ledger: MagicMock,
    mock_store_ledger: MagicMock,
    mock_send_conf: MagicMock,
    mock_tag: MagicMock,
) -> None:
    mock_ssm.side_effect = lambda name: {"/test/api-key": "key", "/test/senders": "allowed@example.com"}[name]
    mock_parse.return_value = _make_parsed_email(subject="FORCE_STORE this receipt")
    mock_check.return_value = [_make_eligibility_result(is_eligible=False)]

    from hsa_receipt_archiver.handler import _handle

    result = _handle(_make_ses_event())
    assert result["statusCode"] == 200
    mock_store_receipt.assert_called_once()
    mock_send_conf.assert_called_once()


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler.tag_raw_email")
@patch("hsa_receipt_archiver.handler.send_confirmation")
@patch("hsa_receipt_archiver.handler.store_ledger")
@patch("hsa_receipt_archiver.handler.fetch_ledger", return_value=None)
@patch("hsa_receipt_archiver.handler.store_receipt", return_value="s3://b/r.pdf")
@patch("hsa_receipt_archiver.handler.convert_to_pdfa", return_value=b"pdf")
@patch("hsa_receipt_archiver.handler.check_hsa_eligibility")
@patch("hsa_receipt_archiver.handler.parse_ses_email")
@patch("hsa_receipt_archiver.handler.fetch_raw_email", return_value=b"raw")
@patch("hsa_receipt_archiver.handler._get_ssm_param")
def test_multiple_results_share_pdf_uri(
    mock_ssm: MagicMock,
    mock_fetch: MagicMock,
    mock_parse: MagicMock,
    mock_check: MagicMock,
    mock_convert: MagicMock,
    mock_store_receipt: MagicMock,
    mock_fetch_ledger: MagicMock,
    mock_store_ledger: MagicMock,
    mock_send_conf: MagicMock,
    mock_tag: MagicMock,
) -> None:
    mock_ssm.side_effect = lambda name: {"/test/api-key": "key", "/test/senders": "allowed@example.com"}[name]
    mock_parse.return_value = _make_parsed_email()
    mock_check.return_value = [
        _make_eligibility_result(description="Visit 1"),
        _make_eligibility_result(description="Visit 2"),
    ]

    from hsa_receipt_archiver.handler import _handle

    _handle(_make_ses_event())

    mock_store_receipt.assert_called_once()
    assert mock_send_conf.call_count == 2
    assert mock_store_ledger.call_count == 2


@patch.dict(os.environ, ENV_VARS)
@patch("hsa_receipt_archiver.handler.tag_raw_email")
@patch("hsa_receipt_archiver.handler.send_confirmation")
@patch("hsa_receipt_archiver.handler.store_ledger")
@patch("hsa_receipt_archiver.handler.fetch_ledger", return_value=None)
@patch("hsa_receipt_archiver.handler.store_receipt", return_value="s3://b/r.pdf")
@patch("hsa_receipt_archiver.handler.convert_to_pdfa", return_value=b"pdf")
@patch("hsa_receipt_archiver.handler.check_hsa_eligibility")
@patch("hsa_receipt_archiver.handler.parse_ses_email")
@patch("hsa_receipt_archiver.handler.fetch_raw_email", return_value=b"raw")
@patch("hsa_receipt_archiver.handler._get_ssm_param")
def test_both_dates_none_with_force_store_uses_today(
    mock_ssm: MagicMock,
    mock_fetch: MagicMock,
    mock_parse: MagicMock,
    mock_check: MagicMock,
    mock_convert: MagicMock,
    mock_store_receipt: MagicMock,
    mock_fetch_ledger: MagicMock,
    mock_store_ledger: MagicMock,
    mock_send_conf: MagicMock,
    mock_tag: MagicMock,
) -> None:
    mock_ssm.side_effect = lambda name: {"/test/api-key": "key", "/test/senders": "allowed@example.com"}[name]
    mock_parse.return_value = _make_parsed_email(subject="FORCE_STORE")
    mock_check.return_value = [
        _make_eligibility_result(is_eligible=False, service_date=None, payment_date=None),
    ]

    from hsa_receipt_archiver.handler import _handle

    _handle(_make_ses_event())

    entry_arg = mock_send_conf.call_args[0][2]
    assert isinstance(entry_arg, LedgerEntry)
    assert entry_arg.payment_date == datetime.now(tz=UTC).date()


def test_parse_date_valid_string() -> None:
    from hsa_receipt_archiver.handler import _parse_date

    result = _parse_date("2025-03-15")
    assert result == date(2025, 3, 15)


def test_parse_date_none_returns_none() -> None:
    from hsa_receipt_archiver.handler import _parse_date

    assert _parse_date(None) is None


def test_today_returns_utc_date() -> None:
    from hsa_receipt_archiver.handler import _today

    result = _today()
    assert result == datetime.now(tz=UTC).date()
