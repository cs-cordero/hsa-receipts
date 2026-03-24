"""API Gateway Lambda handler for the HSA web UI."""

import base64
import csv
import io
import json
import logging
import uuid
from typing import Any

import boto3

from corderohq.archiver.ledger import create_empty_ledger
from corderohq.aws.s3 import (
    delete_object,
    fetch_ledger,
    generate_presigned_receipt_url,
    list_receipt_keys,
    store_ledger,
    store_upload,
)
from corderohq.util import get_env_var

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
        elif path == "/receipt" and method == "GET":
            return _get_receipt(event)
        elif path == "/receipt" and method == "POST":
            return _post_receipt(event)
        elif path == "/receipt" and method == "DELETE":
            return _delete_receipt(event)
        elif path == "/orphaned-receipts" and method == "GET":
            return _get_orphaned_receipts()
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


def _get_receipt(event: dict[str, Any]) -> dict[str, Any]:
    key = (event.get("queryStringParameters") or {}).get("key", "")
    if not key:
        return _response(400, "query parameter 'key' is required")
    if not key.startswith("receipts/"):
        return _response(403, "Access denied")

    bucket = get_env_var("BUCKET_NAME")
    url = generate_presigned_receipt_url(bucket, key)
    return _json_response(200, json.dumps({"url": url}))


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
    store_only = body.get("store_only", False)

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
                "store_only": store_only,
            }
        ),
    )

    result = json.loads(response["Payload"].read())
    status = result.get("statusCode", 500)
    result_body = result.get("body", "{}")

    return _json_response(status, result_body)


def _delete_receipt(event: dict[str, Any]) -> dict[str, Any]:
    key = (event.get("queryStringParameters") or {}).get("key", "")
    if not key:
        return _response(400, "query parameter 'key' is required")
    if not key.startswith("receipts/"):
        return _response(403, "Access denied")

    bucket = get_env_var("BUCKET_NAME")
    delete_object(bucket, key)
    return _json_response(200, json.dumps({"deleted": key}))


def _get_orphaned_receipts() -> dict[str, Any]:
    bucket = get_env_var("BUCKET_NAME")

    receipt_keys = list_receipt_keys(bucket)
    ledger_csv = fetch_ledger(bucket)

    ledger_uris: set[str] = set()
    ledger_rows_with_uri: list[dict[str, str]] = []
    if ledger_csv is not None:
        reader = csv.DictReader(io.StringIO(ledger_csv))
        for row in reader:
            uri = row.get("Receipt S3 URI", "").strip()
            if uri:
                ledger_uris.add(uri)
                ledger_rows_with_uri.append(dict(row))

    s3_uris = {f"s3://{bucket}/{key}" for key in receipt_keys}

    orphaned = sorted(s3_uris - ledger_uris)

    broken: list[dict[str, str]] = []
    for row in ledger_rows_with_uri:
        uri = row.get("Receipt S3 URI", "").strip()
        if uri and uri not in s3_uris:
            broken.append(row)

    return _json_response(200, json.dumps({"orphaned_receipts": orphaned, "broken_references": broken}))


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
