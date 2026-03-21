"""Tests for web_handler module."""

import base64
import json
import os
from unittest.mock import MagicMock, patch

from hsa_receipt_archiver.web_handler import handle

ENV_VARS = {"BUCKET_NAME": "test-bucket", "PROCESSOR_FUNCTION_NAME": "hsa-receipt-archiver"}

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


class TestPostReceipt:
    def _make_receipt_body(self, **overrides: object) -> str:
        defaults: dict[str, object] = {
            "filename": "receipt.pdf",
            "content_type": "application/pdf",
            "data": base64.b64encode(b"pdf-data").decode("ascii"),
            "force_store": False,
        }
        defaults.update(overrides)
        return json.dumps(defaults)

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler._LAMBDA_CLIENT")
    @patch("hsa_receipt_archiver.web_handler.store_upload")
    def test_happy_path(self, mock_upload: MagicMock, mock_lambda: MagicMock) -> None:
        mock_payload = MagicMock()
        mock_payload.read.return_value = json.dumps({"statusCode": 200, "body": '{"entries": []}'}).encode()
        mock_lambda.invoke.return_value = {"Payload": mock_payload}

        result = handle(_make_event("POST", "/receipt", body=self._make_receipt_body()), None)

        assert result["statusCode"] == 200
        assert result["headers"]["Content-Type"] == "application/json"
        mock_upload.assert_called_once()
        mock_lambda.invoke.assert_called_once()
        invoke_args = mock_lambda.invoke.call_args
        assert invoke_args[1]["FunctionName"] == "hsa-receipt-archiver"
        assert invoke_args[1]["InvocationType"] == "RequestResponse"
        payload = json.loads(invoke_args[1]["Payload"])
        assert payload["source"] == "web-upload"
        assert payload["content_type"] == "application/pdf"

    @patch.dict(os.environ, ENV_VARS)
    def test_missing_body_returns_400(self) -> None:
        result = handle(_make_event("POST", "/receipt"), None)

        assert result["statusCode"] == 400

    @patch.dict(os.environ, ENV_VARS)
    def test_missing_fields_returns_400(self) -> None:
        result = handle(_make_event("POST", "/receipt", body=json.dumps({"filename": "x"})), None)

        assert result["statusCode"] == 400

    @patch.dict(os.environ, ENV_VARS)
    def test_unsupported_content_type_returns_400(self) -> None:
        body = self._make_receipt_body(content_type="text/plain")
        result = handle(_make_event("POST", "/receipt", body=body), None)

        assert result["statusCode"] == 400
        assert "Unsupported" in result["body"]

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler._LAMBDA_CLIENT")
    @patch("hsa_receipt_archiver.web_handler.store_upload")
    def test_saves_to_raw_uploads_prefix(self, mock_upload: MagicMock, mock_lambda: MagicMock) -> None:
        mock_payload = MagicMock()
        mock_payload.read.return_value = json.dumps({"statusCode": 200, "body": "{}"}).encode()
        mock_lambda.invoke.return_value = {"Payload": mock_payload}

        handle(_make_event("POST", "/receipt", body=self._make_receipt_body()), None)

        upload_key = mock_upload.call_args[0][1]
        assert upload_key.startswith("raw-uploads/")
        assert upload_key.endswith(".pdf")


class TestRouting:
    @patch.dict(os.environ, ENV_VARS)
    def test_unknown_path_returns_404(self) -> None:
        result = handle(_make_event("GET", "/unknown"), None)

        assert result["statusCode"] == 404

    @patch.dict(os.environ, ENV_VARS)
    def test_wrong_method_returns_404(self) -> None:
        result = handle(_make_event("DELETE", "/ledger"), None)

        assert result["statusCode"] == 404
