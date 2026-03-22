"""Shared receipt processing logic used by both email and web handlers."""

import logging
from dataclasses import dataclass
from datetime import date

from hsa_receipt_archiver.archiver.ledger import LedgerEntry, add_ledger_entry
from hsa_receipt_archiver.archiver.pdf import convert_to_pdfa, get_page_count
from hsa_receipt_archiver.aws.s3 import fetch_ledger, store_ledger, store_receipt
from hsa_receipt_archiver.claude_client import EligibilityResult, check_hsa_eligibility
from hsa_receipt_archiver.util import parse_date, today

LOGGER = logging.getLogger(__name__)

MAX_PAGES_ALLOWED = 10
MAX_TRANSACTIONS_PER_RECEIPT = 3
EARLIEST_ELIGIBLE_DATE = date(2025, 1, 27)
VALID_PATIENTS = frozenset({"CHRIS", "JILLIAN", "KAYA", "MATEO", "UNKNOWN"})


@dataclass
class RejectionDetail:
    """Details about a rejected (ineligible) receipt."""

    filename: str
    description: str
    reasoning: str


@dataclass
class ProcessingResult:
    """Result of processing a single attachment through the receipt pipeline."""

    entries: list[LedgerEntry]
    rejections: list[RejectionDetail]
    receipt_s3_uri: str | None


def process_attachment(
    data: bytes,
    content_type: str,
    filename: str,
    force_store: bool,
    api_key: str,
    bucket: str,
    store_only: bool = False,
) -> ProcessingResult:
    """Analyze a receipt, convert to PDF/A, store in S3, and update the ledger.

    Does NOT send notifications — the caller decides how to notify.
    """
    if store_only:
        return _store_only(data, content_type, filename, bucket)

    results = _analyze_receipt(api_key, data, content_type)

    if len(results) > MAX_TRANSACTIONS_PER_RECEIPT:
        raise ValueError(
            f"Receipt '{filename}' has {len(results)} transactions "
            f"(max {MAX_TRANSACTIONS_PER_RECEIPT}). Claude Haiku is unreliable when "
            "extracting this many transactions from a single receipt and cannot be "
            "trusted. Manual entry is required for this receipt."
        )

    eligible_results: list[EligibilityResult] = []
    rejections: list[RejectionDetail] = []
    for result in results:
        if not result.is_eligible and not force_store:
            rejections.append(RejectionDetail(filename, result.description, result.reasoning))
            LOGGER.info("Rejected receipt: %s — %s", result.description, result.reasoning)
            continue

        service_date = parse_date(result.service_date)
        payment_date = parse_date(result.payment_date)
        effective_date = service_date or payment_date or today()
        if effective_date < EARLIEST_ELIGIBLE_DATE:
            rejections.append(
                RejectionDetail(
                    filename,
                    result.description,
                    f"Service date {effective_date.isoformat()} is before the earliest eligible date "
                    f"({EARLIEST_ELIGIBLE_DATE.isoformat()}). This receipt predates the HSA account.",
                )
            )
            LOGGER.info("Rejected receipt: %s — date %s too old", result.description, effective_date)
            continue

        eligible_results.append(result)

    if not eligible_results:
        return ProcessingResult(entries=[], rejections=rejections, receipt_s3_uri=None)

    pdf_data = convert_to_pdfa(data, content_type)
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
                bucket, pdf_data, receipt_date_str, result.provider or "Unknown", result.short_description
            )

        entry = LedgerEntry(
            service_date=service_date,
            payment_date=payment_date,
            provider=result.provider or "Unknown",
            patient=result.patient if result.patient in VALID_PATIENTS else "UNKNOWN",
            category=result.category,
            description=result.description,
            amount=result.amount or 0.0,
            receipt_s3_uri=receipt_uri,
        )

        ledger_csv = fetch_ledger(bucket)
        updated_ledger = add_ledger_entry(ledger_csv, entry)
        store_ledger(bucket, updated_ledger)
        entries.append(entry)

        LOGGER.info("Archived receipt: %s at %s", result.description, receipt_uri)

    return ProcessingResult(entries=entries, rejections=rejections, receipt_s3_uri=receipt_uri)


def _store_only(data: bytes, content_type: str, filename: str, bucket: str) -> ProcessingResult:
    """Convert to PDF/A and store in S3 without Claude analysis or ledger update."""
    pdf_data = convert_to_pdfa(data, content_type)
    name_stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    receipt_uri = store_receipt(bucket, pdf_data, today().isoformat(), "Manual", name_stem)
    LOGGER.info("Store-only: archived %s at %s", filename, receipt_uri)
    return ProcessingResult(entries=[], rejections=[], receipt_s3_uri=receipt_uri)


def _analyze_receipt(api_key: str, data: bytes, content_type: str) -> list[EligibilityResult]:
    """Send a receipt to Claude for analysis."""
    if content_type == "application/pdf":
        page_count = get_page_count(data)
        if page_count > MAX_PAGES_ALLOWED:
            raise ValueError(
                f"PDF has {page_count} pages (max {MAX_PAGES_ALLOWED}). "
                "Split the document into smaller files and re-send."
            )

    return check_hsa_eligibility(api_key, data, content_type)
