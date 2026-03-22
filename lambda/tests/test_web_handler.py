"""Tests for web_handler module."""

import base64
import json
import os
import typing
from unittest.mock import MagicMock, patch

from hsa_receipt_archiver.web_handler import handle

ENV_VARS = {"BUCKET_NAME": "test-bucket", "PROCESSOR_FUNCTION_NAME": "hsa-receipt-archiver"}

SAMPLE_CSV = "Id,Service Date,Payment Date,Vendor/Provider\n1,2024-01-01,2024-01-02,Dr. Smith\n"


def _make_event(
    method: str,
    path: str,
    body: str | None = None,
    base64_encode: bool = False,
    email: str = "user@example.com",
    query_params: dict[str, str] | None = None,
) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"email": email, "sub": "abc-123"}}},
        },
        "rawPath": path,
        "isBase64Encoded": base64_encode,
        "body": None,
    }
    if query_params is not None:
        event["queryStringParameters"] = query_params
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

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler._LAMBDA_CLIENT")
    @patch("hsa_receipt_archiver.web_handler.store_upload")
    def test_store_only_flag_passed_to_processor(self, mock_upload: MagicMock, mock_lambda: MagicMock) -> None:
        mock_payload = MagicMock()
        mock_payload.read.return_value = json.dumps(
            {"statusCode": 200, "body": '{"receipt_s3_uri": "s3://b/r.pdf"}'}
        ).encode()
        mock_lambda.invoke.return_value = {"Payload": mock_payload}

        body = self._make_receipt_body(store_only=True)
        handle(_make_event("POST", "/receipt", body=body), None)

        payload = json.loads(mock_lambda.invoke.call_args[1]["Payload"])
        assert payload["store_only"] is True


class TestGetReceipt:
    @patch.dict(os.environ, ENV_VARS)
    @patch(
        "hsa_receipt_archiver.web_handler.generate_presigned_receipt_url",
        return_value="https://s3.amazonaws.com/presigned",
    )
    def test_returns_presigned_url(self, mock_presign: MagicMock) -> None:
        event = _make_event("GET", "/receipt", query_params={"key": "receipts/2025/file.pdf"})
        result = handle(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["url"] == "https://s3.amazonaws.com/presigned"
        mock_presign.assert_called_once_with("test-bucket", "receipts/2025/file.pdf")

    @patch.dict(os.environ, ENV_VARS)
    def test_invalid_prefix_returns_403(self) -> None:
        event = _make_event("GET", "/receipt", query_params={"key": "raw-emails/something"})
        result = handle(event, None)

        assert result["statusCode"] == 403

    @patch.dict(os.environ, ENV_VARS)
    def test_missing_key_returns_400(self) -> None:
        event = _make_event("GET", "/receipt")
        result = handle(event, None)

        assert result["statusCode"] == 400


class TestDeleteReceipt:
    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.delete_object")
    def test_deletes_receipt(self, mock_delete: MagicMock) -> None:
        event = _make_event("DELETE", "/receipt", query_params={"key": "receipts/2024/file.pdf"})
        result = handle(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["deleted"] == "receipts/2024/file.pdf"
        mock_delete.assert_called_once_with("test-bucket", "receipts/2024/file.pdf")

    @patch.dict(os.environ, ENV_VARS)
    def test_missing_key_returns_400(self) -> None:
        event = _make_event("DELETE", "/receipt")
        result = handle(event, None)

        assert result["statusCode"] == 400

    @patch.dict(os.environ, ENV_VARS)
    def test_invalid_prefix_returns_403(self) -> None:
        event = _make_event("DELETE", "/receipt", query_params={"key": "raw-emails/something"})
        result = handle(event, None)

        assert result["statusCode"] == 403


class TestGetOrphanedReceipts:
    LEDGER_WITH_URIS = (
        "Id,Service Date,Payment Date,Vendor/Provider,Patient/For,Category,"
        "Description,Amount,Receipt S3 URI,Reimbursed,Notes,Prob. of Duplicate\n"
        "1,2024-01-01,2024-01-02,Dr. Smith,CHRIS,Medical,Visit,100.00,"
        "s3://test-bucket/receipts/2024/exists.pdf,No,,\n"
        "2,2024-06-01,2024-06-02,Dr. Jones,CHRIS,Dental,Cleaning,200.00,"
        "s3://test-bucket/receipts/2024/missing.pdf,No,,\n"
    )

    @patch.dict(os.environ, ENV_VARS)
    @patch(
        "hsa_receipt_archiver.web_handler.list_receipt_keys",
        return_value=["receipts/2024/exists.pdf", "receipts/2024/orphan.pdf"],
    )
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger")
    def test_returns_orphaned_and_broken(self, mock_fetch: MagicMock, mock_list: MagicMock) -> None:
        mock_fetch.return_value = self.LEDGER_WITH_URIS
        result = handle(_make_event("GET", "/orphaned-receipts"), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "s3://test-bucket/receipts/2024/orphan.pdf" in body["orphaned_receipts"]
        assert "s3://test-bucket/receipts/2024/exists.pdf" not in body["orphaned_receipts"]
        assert len(body["broken_references"]) == 1
        assert body["broken_references"][0]["Vendor/Provider"] == "Dr. Jones"

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.list_receipt_keys", return_value=[])
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", return_value=None)
    def test_handles_no_ledger(self, mock_fetch: MagicMock, mock_list: MagicMock) -> None:
        result = handle(_make_event("GET", "/orphaned-receipts"), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["orphaned_receipts"] == []
        assert body["broken_references"] == []

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.list_receipt_keys", side_effect=Exception("S3 error"))
    def test_returns_500_on_error(self, mock_list: MagicMock) -> None:
        result = handle(_make_event("GET", "/orphaned-receipts"), None)

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


class TestSecurityHeaders:
    """All responses must include defense-in-depth security headers."""

    EXPECTED_HEADERS: typing.ClassVar[dict[str, str]] = {
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Cache-Control": "no-store",
    }

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", return_value=SAMPLE_CSV)
    def test_get_ledger_has_security_headers(self, mock_fetch: MagicMock) -> None:
        result = handle(_make_event("GET", "/ledger"), None)

        for header, value in self.EXPECTED_HEADERS.items():
            assert result["headers"][header] == value

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.store_ledger")
    def test_put_ledger_has_security_headers(self, mock_store: MagicMock) -> None:
        result = handle(_make_event("PUT", "/ledger", body=SAMPLE_CSV), None)

        for header, value in self.EXPECTED_HEADERS.items():
            assert result["headers"][header] == value

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler._LAMBDA_CLIENT")
    @patch("hsa_receipt_archiver.web_handler.store_upload")
    def test_post_receipt_has_security_headers(self, mock_upload: MagicMock, mock_lambda: MagicMock) -> None:
        mock_payload = MagicMock()
        mock_payload.read.return_value = json.dumps({"statusCode": 200, "body": "{}"}).encode()
        mock_lambda.invoke.return_value = {"Payload": mock_payload}

        body = json.dumps(
            {
                "filename": "receipt.pdf",
                "content_type": "application/pdf",
                "data": base64.b64encode(b"pdf-data").decode("ascii"),
            }
        )
        result = handle(_make_event("POST", "/receipt", body=body), None)

        for header, value in self.EXPECTED_HEADERS.items():
            assert result["headers"][header] == value

    @patch.dict(os.environ, ENV_VARS)
    def test_error_response_has_security_headers(self) -> None:
        result = handle(_make_event("GET", "/unknown"), None)

        for header, value in self.EXPECTED_HEADERS.items():
            assert result["headers"][header] == value

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", side_effect=Exception("boom"))
    def test_500_response_has_security_headers(self, mock_fetch: MagicMock) -> None:
        result = handle(_make_event("GET", "/ledger"), None)

        assert result["statusCode"] == 500
        for header, value in self.EXPECTED_HEADERS.items():
            assert result["headers"][header] == value


class TestAuditLogging:
    """Requests must be logged with the authenticated user's email."""

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", return_value=SAMPLE_CSV)
    def test_logs_user_email_on_request(self, mock_fetch: MagicMock) -> None:
        with patch("hsa_receipt_archiver.web_handler.LOGGER") as mock_logger:
            handle(_make_event("GET", "/ledger", email="alice@example.com"), None)

            mock_logger.info.assert_any_call("Request from %s: %s %s", "alice@example.com", "GET", "/ledger")

    @patch.dict(os.environ, ENV_VARS)
    @patch("hsa_receipt_archiver.web_handler.fetch_ledger", return_value=SAMPLE_CSV)
    def test_logs_unknown_when_no_claims(self, mock_fetch: MagicMock) -> None:
        event = _make_event("GET", "/ledger")
        del event["requestContext"]["authorizer"]

        with patch("hsa_receipt_archiver.web_handler.LOGGER") as mock_logger:
            handle(event, None)

            mock_logger.info.assert_any_call("Request from %s: %s %s", "unknown", "GET", "/ledger")
