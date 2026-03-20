"""Main Lambda handler for processing HSA receipt emails."""

import logging
from datetime import date
from email.utils import parseaddr
from typing import Any

from hsa_receipt_archiver.archiver.ledger import LedgerEntry, add_ledger_entry
from hsa_receipt_archiver.archiver.pdf import convert_to_pdfa, get_page_count
from hsa_receipt_archiver.aws.s3 import (
    fetch_ledger,
    fetch_raw_email,
    store_ledger,
    store_receipt,
    tag_raw_email,
)
from hsa_receipt_archiver.aws.ses import Attachment, parse_ses_email
from hsa_receipt_archiver.aws.sns import notify_detailed_failure, notify_failure, notify_rejection, notify_success
from hsa_receipt_archiver.aws.ssm import get_ssm_param
from hsa_receipt_archiver.claude_client import EligibilityResult, check_hsa_eligibility
from hsa_receipt_archiver.util import get_env_var, parse_date, today

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

BUCKET_NAME = get_env_var("BUCKET_NAME")
SSM_API_KEY_PARAM = get_env_var("SSM_API_KEY_PARAM")
SSM_ALLOWED_SENDERS_PARAM = get_env_var("SSM_ALLOWED_SENDERS_PARAM")

FORCE_STORE_PREFIX = "FORCE_STORE"
MAX_PAGES_ALLOWED = 10
MAX_TRANSACTIONS_PER_RECEIPT = 3
EARLIEST_ELIGIBLE_DATE = date(2025, 1, 27)


def process_receipt(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process an incoming SES email event."""
    try:
        return _handle(event)
    except Exception as exc:
        LOGGER.exception("Failed to process receipt")
        notify_detailed_failure("Top-level failure in process_receipt", exc)
        return {"statusCode": 500, "body": "Internal error"}


def _handle(event: dict[str, Any]) -> dict[str, Any]:
    ses_record = event["Records"][0]["ses"]
    mail = ses_record["mail"]
    message_id = mail["messageId"]

    receipt = ses_record["receipt"]
    raw_email_key = f"raw-emails/{message_id}"
    LOGGER.info("Processing email %s", message_id)

    spf = receipt.get("spfVerdict", {}).get("status", "GRAY")
    dkim = receipt.get("dkimVerdict", {}).get("status", "GRAY")
    if spf != "PASS" or dkim != "PASS":
        LOGGER.warning("Email authentication failed: SPF=%s, DKIM=%s", spf, dkim)
        return {"statusCode": 403, "body": "Email authentication failed"}

    raw_email = fetch_raw_email(BUCKET_NAME, raw_email_key)
    parsed = parse_ses_email(raw_email)

    _, sender_email = parseaddr(parsed.sender)
    sender_email = sender_email.lower()

    allowed_senders = get_ssm_param(SSM_ALLOWED_SENDERS_PARAM)
    allowed_set = {s.strip().lower() for s in allowed_senders.split(",")}
    if sender_email not in allowed_set:
        LOGGER.warning("Unauthorized sender: %s", sender_email)
        return {"statusCode": 403, "body": "Unauthorized sender"}

    if not parsed.attachments:
        LOGGER.warning("No attachments found in email from %s", sender_email)
        return {"statusCode": 400, "body": "No attachments"}

    force_store = FORCE_STORE_PREFIX in parsed.body.upper()
    api_key = get_ssm_param(SSM_API_KEY_PARAM)

    failed_attachments: list[str] = []
    for i, attachment in enumerate(parsed.attachments):
        LOGGER.info(
            "Attachment %d/%d: filename=%s, content_type=%s, size=%d bytes",
            i + 1,
            len(parsed.attachments),
            attachment.filename,
            attachment.content_type,
            len(attachment.data),
        )
        try:
            _process_attachment(attachment, force_store, api_key)
        except Exception as exc:
            LOGGER.exception("Failed to process attachment %s", attachment.filename)
            notify_failure(f"Failed to process attachment: {attachment.filename}")
            notify_detailed_failure(f"Failed to process attachment: {attachment.filename}", exc)
            failed_attachments.append(attachment.filename)

    tag_raw_email(BUCKET_NAME, raw_email_key)

    if failed_attachments:
        body = f"Failed attachments: {', '.join(failed_attachments)}"
        if len(failed_attachments) == len(parsed.attachments):
            return {"statusCode": 500, "body": body}
        return {"statusCode": 207, "body": body}

    return {"statusCode": 200, "body": "Processed"}


def _process_attachment(attachment: "Attachment", force_store: bool, api_key: str) -> None:
    results = _analyze_receipt(api_key, attachment.data, attachment.content_type)

    if len(results) > MAX_TRANSACTIONS_PER_RECEIPT:
        raise ValueError(
            f"Receipt '{attachment.filename}' has {len(results)} transactions "
            f"(max {MAX_TRANSACTIONS_PER_RECEIPT}). Claude Haiku is unreliable when "
            "extracting this many transactions from a single receipt and cannot be "
            "trusted. Manual entry is required for this receipt."
        )

    eligible_results = []
    for result in results:
        if not result.is_eligible and not force_store:
            notify_rejection(attachment.filename, result.description, result.reasoning)
            LOGGER.info("Rejected receipt: %s — %s", result.description, result.reasoning)
        else:
            eligible_results.append(result)

    if not eligible_results:
        return

    pdf_data = convert_to_pdfa(attachment.data, attachment.content_type)
    receipt_uri: str | None = None
    entries: list[LedgerEntry] = []

    for result in eligible_results:
        service_date = parse_date(result.service_date)
        payment_date = parse_date(result.payment_date)
        if service_date is None and payment_date is None:
            payment_date = today()

        if receipt_uri is None:
            receipt_date_str = (service_date or payment_date or today()).isoformat()
            receipt_uri = store_receipt(
                BUCKET_NAME, pdf_data, receipt_date_str, result.provider or "Unknown", result.short_description
            )

        entry = LedgerEntry(
            service_date=service_date,
            payment_date=payment_date,
            provider=result.provider or "Unknown",
            patient=result.patient or "",
            category=result.category,
            description=result.description,
            amount=result.amount or 0.0,
            receipt_s3_uri=receipt_uri,
        )

        ledger_csv = fetch_ledger(BUCKET_NAME)
        updated_ledger = add_ledger_entry(ledger_csv, entry)
        store_ledger(BUCKET_NAME, updated_ledger)
        entries.append(entry)

        LOGGER.info("Archived receipt: %s at %s", result.description, receipt_uri)

    notify_success(entries)


def _analyze_receipt(api_key: str, data: bytes, content_type: str) -> list["EligibilityResult"]:
    """Send a receipt to Claude for analysis."""
    if content_type == "application/pdf":
        page_count = get_page_count(data)
        if page_count > MAX_PAGES_ALLOWED:
            raise ValueError(
                f"PDF has {page_count} pages (max {MAX_PAGES_ALLOWED}). "
                "Split the document into smaller files and re-send."
            )

    return check_hsa_eligibility(api_key, data, content_type)
