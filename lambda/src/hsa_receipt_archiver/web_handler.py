"""API Gateway Lambda handler for the HSA web UI."""

import base64
import logging
from typing import Any

from hsa_receipt_archiver.archiver.ledger import create_empty_ledger
from hsa_receipt_archiver.aws.s3 import fetch_ledger, store_ledger
from hsa_receipt_archiver.util import get_env_var

LOGGER = logging.getLogger(__name__)


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route API Gateway HTTP API requests."""
    try:
        method = event["requestContext"]["http"]["method"]
        path = event["rawPath"]

        if path == "/ledger" and method == "GET":
            return _get_ledger()
        elif path == "/ledger" and method == "PUT":
            return _put_ledger(event)
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


def _csv_response(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/csv"},
        "body": body,
    }


def _response(status: int, message: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/plain"},
        "body": message,
    }
