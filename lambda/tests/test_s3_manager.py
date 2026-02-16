"""Tests for s3_manager module."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from hsa_receipt_archiver.s3_manager import (
    _key_exists,
    _sanitize,
    fetch_ledger,
    fetch_raw_email,
    store_ledger,
    store_receipt,
    tag_raw_email,
)


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_fetch_raw_email_returns_bytes(mock_s3: MagicMock) -> None:
    mock_body = MagicMock()
    mock_body.read.return_value = b"raw email content"
    mock_s3.get_object.return_value = {"Body": mock_body}

    result = fetch_raw_email("bucket", "raw-emails/msg-123")
    assert result == b"raw email content"
    mock_s3.get_object.assert_called_once_with(Bucket="bucket", Key="raw-emails/msg-123")


@patch("hsa_receipt_archiver.s3_manager._key_exists", return_value=False)
@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_store_receipt_generates_correct_key(mock_s3: MagicMock, _mock_exists: MagicMock) -> None:
    uri = store_receipt("bucket", b"pdf-data", "2025-01-15", "Dr Smith", "Office_Visit")
    assert uri == "s3://bucket/receipts/2025/2025-01-15_Dr_Smith_Office_Visit.pdf"
    mock_s3.put_object.assert_called_once()


@patch("hsa_receipt_archiver.s3_manager._key_exists")
@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_store_receipt_collision_appends_counter(mock_s3: MagicMock, mock_exists: MagicMock) -> None:
    mock_exists.side_effect = [True, False]
    uri = store_receipt("bucket", b"pdf-data", "2025-01-15", "Dr Smith", "Medical")
    assert uri == "s3://bucket/receipts/2025/2025-01-15_Dr_Smith_Medical_2.pdf"


@patch("hsa_receipt_archiver.s3_manager._key_exists")
@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_store_receipt_multiple_collisions(mock_s3: MagicMock, mock_exists: MagicMock) -> None:
    mock_exists.side_effect = [True, True, True, False]
    uri = store_receipt("bucket", b"pdf-data", "2025-01-15", "Dr Smith", "Medical")
    assert uri == "s3://bucket/receipts/2025/2025-01-15_Dr_Smith_Medical_4.pdf"


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_fetch_ledger_returns_csv_string(mock_s3: MagicMock) -> None:
    mock_body = MagicMock()
    mock_body.read.return_value = b"header1,header2\nval1,val2\n"
    mock_s3.get_object.return_value = {"Body": mock_body}

    result = fetch_ledger("bucket")
    assert result == "header1,header2\nval1,val2\n"


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_fetch_ledger_returns_none_on_nosuchkey(mock_s3: MagicMock) -> None:
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": ""}},
        "GetObject",
    )
    result = fetch_ledger("bucket")
    assert result is None


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_fetch_ledger_raises_other_client_errors(mock_s3: MagicMock) -> None:
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": ""}},
        "GetObject",
    )
    with pytest.raises(ClientError):
        fetch_ledger("bucket")


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_store_ledger_encodes_utf8(mock_s3: MagicMock) -> None:
    store_ledger("bucket", "csv-content")
    mock_s3.put_object.assert_called_once_with(
        Bucket="bucket",
        Key="ledger/hsa-receipts.csv",
        Body=b"csv-content",
        ContentType="text/csv",
    )


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_tag_raw_email_sets_processed_tag(mock_s3: MagicMock) -> None:
    tag_raw_email("bucket", "raw-emails/msg-123")
    mock_s3.put_object_tagging.assert_called_once_with(
        Bucket="bucket",
        Key="raw-emails/msg-123",
        Tagging={"TagSet": [{"Key": "status", "Value": "processed"}]},
    )


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_key_exists_returns_true_when_exists(mock_s3: MagicMock) -> None:
    mock_s3.head_object.return_value = {}
    assert _key_exists("bucket", "some-key") is True


@patch("hsa_receipt_archiver.s3_manager.S3_CLIENT")
def test_key_exists_returns_false_on_404(mock_s3: MagicMock) -> None:
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": ""}},
        "HeadObject",
    )
    assert _key_exists("bucket", "some-key") is False


def test_sanitize_replaces_special_chars() -> None:
    assert _sanitize("Dr. Smith & Associates") == "Dr_Smith_Associates"


def test_sanitize_strips_leading_trailing_underscores() -> None:
    assert _sanitize("  hello  ") == "hello"
    assert _sanitize("---test---") == "test"


def test_sanitize_collapses_multiple_special_chars() -> None:
    assert _sanitize("a!!!b") == "a_b"
