"""API Gateway Lambda handler for the HSA web UI."""

import base64
import json
import logging
import uuid
from typing import Any

import boto3

from hsa_receipt_archiver.archiver.ledger import create_empty_ledger
from hsa_receipt_archiver.aws.s3 import fetch_ledger, store_ledger, store_upload
from hsa_receipt_archiver.util import get_env_var

LOGGER = logging.getLogger(__name__)

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

_LAMBDA_CLIENT = boto3.client("lambda")


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route API Gateway HTTP API requests."""
    try:
        method = event["requestContext"]["http"]["method"]
        path = event["rawPath"]

        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        user_email = claims.get("email", "unknown")
        LOGGER.info("Request from %s: %s %s", user_email, method, path)

        if path == "/ledger" and method == "GET":
            return _get_ledger()
        elif path == "/ledger" and method == "PUT":
            return _put_ledger(event)
        elif path == "/receipt" and method == "POST":
            return _post_receipt(event)
        else:
            return _response(404, "Not found")
    except Exception:
        LOGGER.exception("Unhandled error in web handler")
        return _response(500, "Internal server error")


def _get_ledger() -> dict[str, Any]:
    bucket = get_env_var("BUCKET_NAME")
    csv = fetch_ledger(bucket)
    if csv is None:
        csv = create_empty_ledger()
    return _csv_response(200, csv)


def _put_ledger(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if event.get("isBase64Encoded") and body is not None:
        body = base64.b64decode(body).decode("utf-8")
    if not body:
        return _response(400, "Request body is required")

    bucket = get_env_var("BUCKET_NAME")
    store_ledger(bucket, body)
    return _csv_response(200, body)


def _post_receipt(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body", "")
    if event.get("isBase64Encoded") and raw_body:
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    if not raw_body:
        return _response(400, "Request body is required")

    body = json.loads(raw_body)
    filename = body.get("filename", "")
    content_type = body.get("content_type", "")
    file_data_b64 = body.get("data", "")
    force_store = body.get("force_store", False)

    if not filename or not content_type or not file_data_b64:
        return _response(400, "filename, content_type, and data are required")

    if content_type not in ALLOWED_CONTENT_TYPES:
        return _response(400, f"Unsupported content type: {content_type}")

    file_data = base64.b64decode(file_data_b64)
    bucket = get_env_var("BUCKET_NAME")
    processor_function = get_env_var("PROCESSOR_FUNCTION_NAME")

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    upload_key = f"raw-uploads/{uuid.uuid4()}.{ext}"

    store_upload(bucket, upload_key, file_data, content_type)

    response = _LAMBDA_CLIENT.invoke(
        FunctionName=processor_function,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "source": "web-upload",
                "bucket": bucket,
                "key": upload_key,
                "content_type": content_type,
                "filename": filename,
                "force_store": force_store,
            }
        ),
    )

    result = json.loads(response["Payload"].read())
    status = result.get("statusCode", 500)
    result_body = result.get("body", "{}")

    return _json_response(status, result_body)


def _csv_response(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**_SECURITY_HEADERS, "Content-Type": "text/csv"},
        "body": body,
    }


def _json_response(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**_SECURITY_HEADERS, "Content-Type": "application/json"},
        "body": body,
    }


def _response(status: int, message: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**_SECURITY_HEADERS, "Content-Type": "text/plain"},
        "body": message,
    }
