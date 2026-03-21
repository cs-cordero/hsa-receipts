"""Tests for web_handler module."""

import base64
import os
from unittest.mock import MagicMock, patch

from hsa_receipt_archiver.web_handler import handle

ENV_VARS = {"BUCKET_NAME": "test-bucket"}

SAMPLE_CSV = "Id,Service Date,Payment Date,Vendor/Provider\n1,2024-01-01,2024-01-02,Dr. Smith\n"


def _make_event(method: str, path: str, body: str | None = None, base64_encode: bool = False) -> dict:
    event: dict = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "isBase64Encoded": base64_encode,
        "body": None,
    }
    if body is not None:
        if base64_encode:
            event["body"] = base64.b64encode(body.encode("utf-8")).decode("ascii")
        else:
            event["body"] = body
    return event


class TestGetLedger:
    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", return_value=SAMPLE_CSV)
    def test_returns_existing_csv(self, mock_fetch: MagicMock) -> None:
        result = handle(_make_event("GET", "/ledger"), None)

        assert result["statusCode"] == 200
        assert result["headers"]["Content-Type"] == "text/csv"
        assert result["body"] == SAMPLE_CSV
        mock_fetch.assert_called_once_with("test-bucket")

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", return_value=None)
    def test_returns_empty_ledger_when_none_exists(self, mock_fetch: MagicMock) -> None:
        result = handle(_make_event("GET", "/ledger"), None)

        assert result["statusCode"] == 200
        assert result["headers"]["Content-Type"] == "text/csv"
        assert "Id" in result["body"]
        assert "Vendor/Provider" in result["body"]

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", side_effect=Exception("S3 error"))
    def test_returns_500_on_s3_error(self, mock_fetch: MagicMock) -> None:
        result = handle(_make_event("GET", "/ledger"), None)

        assert result["statusCode"] == 500


class TestPutLedger:
    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.store_ledger")
    def test_stores_and_returns_csv(self, mock_store: MagicMock) -> None:
        result = handle(_make_event("PUT", "/ledger", body=SAMPLE_CSV), None)

        assert result["statusCode"] == 200
        assert result["headers"]["Content-Type"] == "text/csv"
        assert result["body"] == SAMPLE_CSV
        mock_store.assert_called_once_with("test-bucket", SAMPLE_CSV)

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.store_ledger")
    def test_handles_base64_encoded_body(self, mock_store: MagicMock) -> None:
        result = handle(_make_event("PUT", "/ledger", body=SAMPLE_CSV, base64_encode=True), None)

        assert result["statusCode"] == 200
        assert result["body"] == SAMPLE_CSV
        mock_store.assert_called_once_with("test-bucket", SAMPLE_CSV)

    @patch.dict(os.environ, ENV_VARS)
    def test_returns_400_when_body_is_missing(self) -> None:
        result = handle(_make_event("PUT", "/ledger"), None)

        assert result["statusCode"] == 400

    @patch.dict(os.environ, ENV_VARS)
    def test_returns_400_when_body_is_empty(self) -> None:
        result = handle(_make_event("PUT", "/ledger", body=""), None)

        assert result["statusCode"] == 400

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.store_ledger", side_effect=Exception("S3 error"))
    def test_returns_500_on_s3_error(self, mock_store: MagicMock) -> None:
        result = handle(_make_event("PUT", "/ledger", body=SAMPLE_CSV), None)

        assert result["statusCode"] == 500


class TestRouting:
    @patch.dict(os.environ, ENV_VARS)
    def test_unknown_path_returns_404(self) -> None:
        result = handle(_make_event("GET", "/unknown"), None)

        assert result["statusCode"] == 404

    @patch.dict(os.environ, ENV_VARS)
    def test_wrong_method_returns_404(self) -> None:
        result = handle(_make_event("DELETE", "/ledger"), None)

        assert result["statusCode"] == 404
