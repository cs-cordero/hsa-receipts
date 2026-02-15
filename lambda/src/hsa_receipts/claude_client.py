"""Claude API client for HSA eligibility determination."""

from dataclasses import dataclass


@dataclass
class EligibilityResult:
    is_eligible: bool
    description: str
    amount: float | None
    provider: str | None
    date: str | None
    reasoning: str


def check_hsa_eligibility(image_data: bytes, content_type: str) -> EligibilityResult:
    """Send a receipt image to Claude and determine HSA eligibility."""
    raise NotImplementedError
