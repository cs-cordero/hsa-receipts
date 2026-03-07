"""Publish notifications to SNS."""

import os
import traceback

import boto3

from hsa_receipt_archiver.ledger_manager import LedgerEntry

SNS_CLIENT = boto3.client("sns")

TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
DETAILED_FAILURE_TOPIC_ARN = os.environ["SNS_DETAILED_FAILURE_TOPIC_ARN"]


def notify_success(entries: list[LedgerEntry]) -> None:
    """Publish a success notification with a formatted table of ledger entries."""
    n = len(entries)
    subject = f"HSA Receipt Archived ({n} item{'s' if n != 1 else ''})"

    rows: list[str] = []
    for entry in entries:
        service_date = entry.service_date.isoformat() if entry.service_date else "N/A"
        payment_date = entry.payment_date.isoformat() if entry.payment_date else "N/A"
        patient = entry.patient or "N/A"
        amount = f"${entry.amount:.2f}"
        rows.append(
            f"  {service_date:<12}  {payment_date:<12}  {entry.provider:<20}  {patient:<15}  "
            f"{entry.category:<10}  {entry.description:<30}  {amount}"
        )

    header = (
        f"  {'Service Date':<12}  {'Payment Date':<12}  {'Provider':<20}  {'Patient/For':<15}  "
        f"{'Category':<10}  {'Description':<30}  Amount"
    )
    separator = "  " + "-" * (len(header) - 2)
    receipt_uri = entries[0].receipt_s3_uri if entries else ""

    message = "\n".join([header, separator, *rows])
    if receipt_uri:
        message += f"\n\nReceipt: {receipt_uri}"

    SNS_CLIENT.publish(TopicArn=TOPIC_ARN, Subject=subject, Message=message)


def notify_failure(message: str) -> None:
    """Publish a failure notification for processing errors."""
    body = (
        "An error occurred while processing your receipt.\n\n"
        f"Error: {message}\n\n"
        "Please try re-sending the email. If the problem persists, "
        "check that the attachment is a supported image (JPEG, PNG, GIF, WebP) or PDF."
    )
    SNS_CLIENT.publish(TopicArn=TOPIC_ARN, Subject="HSA Receipt Processing Failed", Message=body)


def notify_rejection(description: str, reasoning: str) -> None:
    """Publish a rejection notification explaining why a receipt was not eligible."""
    body = (
        f"Your receipt for {description} was determined to not be HSA-eligible.\n\n"
        f"Reasoning: {reasoning}\n\n"
        "If you believe this is incorrect, re-send the same email with the subject "
        'line starting with "FORCE_STORE" to archive it regardless of eligibility.'
    )
    SNS_CLIENT.publish(TopicArn=TOPIC_ARN, Subject="HSA Receipt Not Eligible", Message=body)


def notify_detailed_failure(message: str, exception: BaseException) -> None:
    """Publish detailed failure information (including stack trace) to the detailed failures topic."""
    tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    body = (
        f"Failure context: {message}\n\n"
        f"Exception type: {type(exception).__qualname__}\n"
        f"Exception message: {exception}\n\n"
        f"Stack trace:\n{tb}"
    )
    SNS_CLIENT.publish(
        TopicArn=DETAILED_FAILURE_TOPIC_ARN,
        Subject="HSA Receipt Processing Failed (Detailed)",
        Message=body,
    )
