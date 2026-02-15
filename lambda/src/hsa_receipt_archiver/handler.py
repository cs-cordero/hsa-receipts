"""Main Lambda handler for processing HSA receipt emails."""

from typing import Any


def process_receipt(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process an incoming SES email event.

    1. Parse the email to extract attachments
    2. Validate sender against allowlist
    3. Check rate limits
    4. Send attachment to Claude for HSA eligibility check
    5. If eligible: convert to PDF/A, store, update ledger, send confirmation
    6. If not eligible: send notification email
    """
    raise NotImplementedError
