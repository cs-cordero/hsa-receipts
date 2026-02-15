"""Send notification emails via SES."""


def send_confirmation(recipient: str, description: str, amount: float) -> None:
    """Send a confirmation email that a receipt was processed successfully."""
    raise NotImplementedError


def send_eligibility_question(
    recipient: str,
    description: str,
    reasoning: str,
) -> None:
    """Send an email asking the sender to APPROVE or REJECT the receipt."""
    raise NotImplementedError
