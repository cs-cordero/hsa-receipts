"""Send notification emails via SES."""

import boto3

from hsa_receipt_archiver.ledger_manager import LedgerEntry

SES_CLIENT = boto3.client("ses")


def send_confirmation(from_address: str, recipient: str, entry: LedgerEntry) -> None:
    """Send a confirmation email that a receipt was processed successfully."""
    amount_str = f"${entry.amount:.2f}"
    service_date = entry.service_date.isoformat() if entry.service_date else "N/A"
    payment_date = entry.payment_date.isoformat() if entry.payment_date else "N/A"

    body = (
        "Your receipt has been archived successfully.\n\n"
        "Ledger entry added:\n"
        f"  Service Date:  {service_date}\n"
        f"  Payment Date:  {payment_date}\n"
        f"  Provider:      {entry.provider}\n"
        f"  Category:      {entry.category}\n"
        f"  Description:   {entry.description}\n"
        f"  Amount:        {amount_str}\n"
        f"  Receipt:       {entry.receipt_s3_uri}\n"
    )

    SES_CLIENT.send_email(
        Source=from_address,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": f"HSA Receipt Archived: {entry.description}"},
            "Body": {"Text": {"Data": body}},
        },
    )


def send_error_notice(from_address: str, recipient: str, error_message: str) -> None:
    """Send an email notifying the sender that processing failed."""
    SES_CLIENT.send_email(
        Source=from_address,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": "HSA Receipt Processing Failed"},
            "Body": {
                "Text": {
                    "Data": (
                        "An error occurred while processing your receipt.\n\n"
                        f"Error: {error_message}\n\n"
                        "Please try re-sending the email. If the problem persists, "
                        "check that the attachment is a supported image (JPEG, PNG, GIF, WebP) or PDF."
                    ),
                },
            },
        },
    )


def send_rejection_notice(from_address: str, recipient: str, description: str, reasoning: str) -> None:
    """Send an email explaining why a receipt was rejected, with FORCE_STORE instructions."""
    SES_CLIENT.send_email(
        Source=from_address,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": "HSA Receipt Not Eligible"},
            "Body": {
                "Text": {
                    "Data": (
                        f"Your receipt for {description} was determined to not be HSA-eligible.\n\n"
                        f"Reasoning: {reasoning}\n\n"
                        "If you believe this is incorrect, re-send the same email with the subject "
                        'line starting with "FORCE_STORE" to archive it regardless of eligibility.'
                    ),
                },
            },
        },
    )
