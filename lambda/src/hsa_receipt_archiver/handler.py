"""Main Lambda handler for processing HSA receipt emails."""

import logging
import os
from datetime import UTC, date, datetime
from email.utils import parseaddr
from typing import Any

import boto3

from hsa_receipt_archiver.claude_client import check_hsa_eligibility
from hsa_receipt_archiver.email_parser import Attachment, parse_ses_email
from hsa_receipt_archiver.email_sender import send_confirmation, send_error_notice, send_rejection_notice
from hsa_receipt_archiver.ledger_manager import LedgerEntry, add_ledger_entry
from hsa_receipt_archiver.pdf_converter import convert_to_pdfa
from hsa_receipt_archiver.s3_manager import (
    fetch_ledger,
    fetch_raw_email,
    store_ledger,
    store_receipt,
    tag_raw_email,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BUCKET_NAME = os.environ["BUCKET_NAME"]
DOMAIN_NAME = os.environ["DOMAIN_NAME"]
SSM_API_KEY_PARAM = os.environ["SSM_API_KEY_PARAM"]
SSM_ALLOWED_SENDERS_PARAM = os.environ["SSM_ALLOWED_SENDERS_PARAM"]

FORCE_STORE_PREFIX = "FORCE_STORE"
FROM_ADDRESS = f"receipts@{DOMAIN_NAME}"

_ssm_cache: dict[str, str] = {}
_ssm_client = boto3.client("ssm")


def _get_ssm_param(name: str) -> str:
    """Fetch an SSM parameter, caching across invocations."""
    if name not in _ssm_cache:
        response = _ssm_client.get_parameter(Name=name, WithDecryption=True)
        _ssm_cache[name] = response["Parameter"]["Value"]
    return _ssm_cache[name]


def process_receipt(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process an incoming SES email event."""
    try:
        return _handle(event)
    except Exception:
        logger.exception("Failed to process receipt")
        return {"statusCode": 500, "body": "Internal error"}


def _handle(event: dict[str, Any]) -> dict[str, Any]:
    ses_record = event["Records"][0]["ses"]
    mail = ses_record["mail"]
    message_id = mail["messageId"]

    raw_email_key = f"raw-emails/{message_id}"
    logger.info("Processing email %s", message_id)

    raw_email = fetch_raw_email(BUCKET_NAME, raw_email_key)
    parsed = parse_ses_email(raw_email)

    _, sender_email = parseaddr(parsed.sender)
    sender_email = sender_email.lower()

    allowed_senders = _get_ssm_param(SSM_ALLOWED_SENDERS_PARAM)
    allowed_set = {s.strip().lower() for s in allowed_senders.split(",")}
    if sender_email not in allowed_set:
        logger.warning("Unauthorized sender: %s", sender_email)
        return {"statusCode": 403, "body": "Unauthorized sender"}

    if not parsed.attachments:
        logger.warning("No attachments found in email from %s", sender_email)
        return {"statusCode": 400, "body": "No attachments"}

    force_store = parsed.subject.strip().upper().startswith(FORCE_STORE_PREFIX)
    api_key = _get_ssm_param(SSM_API_KEY_PARAM)

    for i, attachment in enumerate(parsed.attachments):
        logger.info(
            "Attachment %d/%d: filename=%s, content_type=%s, size=%d bytes",
            i + 1,
            len(parsed.attachments),
            attachment.filename,
            attachment.content_type,
            len(attachment.data),
        )
        try:
            _process_attachment(attachment, force_store, api_key, sender_email)
        except Exception:
            logger.exception("Failed to process attachment %s", attachment.filename)
            send_error_notice(FROM_ADDRESS, sender_email, f"Failed to process attachment: {attachment.filename}")

    tag_raw_email(BUCKET_NAME, raw_email_key)
    return {"statusCode": 200, "body": "Processed"}


def _process_attachment(attachment: "Attachment", force_store: bool, api_key: str, sender_email: str) -> None:
    results = check_hsa_eligibility(api_key, attachment.data, attachment.content_type)

    eligible_results = []
    for result in results:
        if not result.is_eligible and not force_store:
            send_rejection_notice(FROM_ADDRESS, sender_email, result.description, result.reasoning)
            logger.info("Rejected receipt: %s — %s", result.description, result.reasoning)
        else:
            eligible_results.append(result)

    if not eligible_results:
        return

    pdf_data = convert_to_pdfa(attachment.data, attachment.content_type)
    receipt_uri: str | None = None

    for result in eligible_results:
        service_date = _parse_date(result.service_date)
        payment_date = _parse_date(result.payment_date)
        if service_date is None and payment_date is None:
            payment_date = _today()

        if receipt_uri is None:
            receipt_date_str = (service_date or payment_date or _today()).isoformat()
            receipt_uri = store_receipt(
                BUCKET_NAME, pdf_data, receipt_date_str, result.provider or "Unknown", result.short_description
            )

        entry = LedgerEntry(
            service_date=service_date,
            payment_date=payment_date,
            provider=result.provider or "Unknown",
            category=result.category,
            description=result.description,
            amount=result.amount or 0.0,
            receipt_s3_uri=receipt_uri,
        )

        ledger_csv = fetch_ledger(BUCKET_NAME)
        updated_ledger = add_ledger_entry(ledger_csv, entry)
        store_ledger(BUCKET_NAME, updated_ledger)

        send_confirmation(FROM_ADDRESS, sender_email, entry)
        logger.info("Archived receipt: %s at %s", result.description, receipt_uri)


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _parse_date(date_str: str | None) -> date | None:
    if date_str is None:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC).date()
