"""Tests for S3 module."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from corderohq.aws.s3 import (
    _key_exists,
    _sanitize,
    delete_object,
    fetch_ledger,
    fetch_raw_email,
    list_receipt_keys,
    store_ledger,
    store_receipt,
    tag_raw_email,
)


@patch("corderohq.aws.s3._S3_CLIENT")
def test_fetch_raw_email_returns_bytes(mock_s3: MagicMock) -> None:
    mock_body = MagicMock()
    mock_body.read.return_value = b"raw email content"
    mock_s3.get_object.return_value = {"Body": mock_body}

    result = fetch_raw_email("bucket", "raw-emails/msg-123")
    assert result == b"raw email content"
    mock_s3.get_object.assert_called_once_with(Bucket="bucket", Key="raw-emails/msg-123")


@patch("corderohq.aws.s3._key_exists", return_value=False)
@patch("corderohq.aws.s3._S3_CLIENT")
def test_store_receipt_generates_correct_key(mock_s3: MagicMock, _mock_exists: MagicMock) -> None:
    uri = store_receipt("bucket", b"pdf-data", "2025-01-15", "Dr Smith", "Office_Visit")
    assert uri == "s3://bucket/receipts/2025/2025-01-15_Dr_Smith_Office_Visit.pdf"
    mock_s3.put_object.assert_called_once()


@patch("corderohq.aws.s3._key_exists")
@patch("corderohq.aws.s3._S3_CLIENT")
def test_store_receipt_collision_appends_counter(mock_s3: MagicMock, mock_exists: MagicMock) -> None:
    mock_exists.side_effect = [True, False]
    uri = store_receipt("bucket", b"pdf-data", "2025-01-15", "Dr Smith", "Medical")
    assert uri == "s3://bucket/receipts/2025/2025-01-15_Dr_Smith_Medical_2.pdf"


@patch("corderohq.aws.s3._key_exists")
@patch("corderohq.aws.s3._S3_CLIENT")
def test_store_receipt_multiple_collisions(mock_s3: MagicMock, mock_exists: MagicMock) -> None:
    mock_exists.side_effect = [True, True, True, False]
    uri = store_receipt("bucket", b"pdf-data", "2025-01-15", "Dr Smith", "Medical")
    assert uri == "s3://bucket/receipts/2025/2025-01-15_Dr_Smith_Medical_4.pdf"


@patch("corderohq.aws.s3._S3_CLIENT")
def test_fetch_ledger_returns_csv_string(mock_s3: MagicMock) -> None:
    mock_body = MagicMock()
    mock_body.read.return_value = b"header1,header2\nval1,val2\n"
    mock_s3.get_object.return_value = {"Body": mock_body}

    result = fetch_ledger("bucket")
    assert result == "header1,header2\nval1,val2\n"


@patch("corderohq.aws.s3._S3_CLIENT")
def test_fetch_ledger_returns_none_on_nosuchkey(mock_s3: MagicMock) -> None:
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": ""}},
        "GetObject",
    )
    result = fetch_ledger("bucket")
    assert result is None


@patch("corderohq.aws.s3._S3_CLIENT")
def test_fetch_ledger_raises_other_client_errors(mock_s3: MagicMock) -> None:
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": ""}},
        "GetObject",
    )
    with pytest.raises(ClientError):
        fetch_ledger("bucket")


@patch("corderohq.aws.s3._S3_CLIENT")
def test_store_ledger_encodes_utf8(mock_s3: MagicMock) -> None:
    store_ledger("bucket", "csv-content")
    mock_s3.put_object.assert_called_once_with(
        Bucket="bucket",
        Key="ledger/hsa-receipts.csv",
        Body=b"csv-content",
        ContentType="text/csv",
    )


@patch("corderohq.aws.s3._S3_CLIENT")
def test_tag_raw_email_sets_processed_tag(mock_s3: MagicMock) -> None:
    tag_raw_email("bucket", "raw-emails/msg-123")
    mock_s3.put_object_tagging.assert_called_once_with(
        Bucket="bucket",
        Key="raw-emails/msg-123",
        Tagging={"TagSet": [{"Key": "status", "Value": "processed"}]},
    )


@patch("corderohq.aws.s3._S3_CLIENT")
def test_key_exists_returns_true_when_exists(mock_s3: MagicMock) -> None:
    mock_s3.head_object.return_value = {}
    assert _key_exists("bucket", "some-key") is True


@patch("corderohq.aws.s3._S3_CLIENT")
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


@patch("corderohq.aws.s3._S3_CLIENT")
def test_list_receipt_keys_returns_keys(mock_s3: MagicMock) -> None:
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "receipts/2024/a.pdf"}, {"Key": "receipts/2024/b.pdf"}]},
        {"Contents": [{"Key": "receipts/2025/c.pdf"}]},
    ]
    mock_s3.get_paginator.return_value = paginator

    result = list_receipt_keys("bucket")
    assert result == ["receipts/2024/a.pdf", "receipts/2024/b.pdf", "receipts/2025/c.pdf"]
    mock_s3.get_paginator.assert_called_once_with("list_objects_v2")
    paginator.paginate.assert_called_once_with(Bucket="bucket", Prefix="receipts/")


@patch("corderohq.aws.s3._S3_CLIENT")
def test_list_receipt_keys_handles_empty_bucket(mock_s3: MagicMock) -> None:
    paginator = MagicMock()
    paginator.paginate.return_value = [{}]
    mock_s3.get_paginator.return_value = paginator

    result = list_receipt_keys("bucket")
    assert result == []


@patch("corderohq.aws.s3._S3_CLIENT")
def test_delete_object_calls_s3(mock_s3: MagicMock) -> None:
    delete_object("bucket", "receipts/2024/file.pdf")
    mock_s3.delete_object.assert_called_once_with(Bucket="bucket", Key="receipts/2024/file.pdf")
