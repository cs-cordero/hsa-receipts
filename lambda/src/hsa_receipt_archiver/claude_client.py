"""Claude API client for HSA eligibility determination."""

import base64
import json
import logging
from dataclasses import dataclass
from typing import Literal, cast, get_args

import anthropic
from anthropic.types import (
    Base64ImageSourceParam,
    Base64PDFSourceParam,
    DocumentBlockParam,
    ImageBlockParam,
    TextBlock,
    TextBlockParam,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an HSA (Health Savings Account) eligibility expert. Analyze the provided receipt \
or statement and determine which expenses are HSA-eligible.

A document may contain multiple transactions. Extract EACH out-of-pocket transaction as a \
separate line item. Only include amounts the patient actually paid — ignore insurance payments, \
adjustments, writedowns, and contractual allowances.

Respond with a JSON array of objects. Each object must contain exactly these fields:
- "is_eligible": boolean
- "description": string describing the item or service
- "short_description": one or two words for a filename, e.g. "Medical", "Dental", "Vision", \
"Pharmacy", or a drug name like "Tylenol". Use underscores between words.
- "category": one of "Medical", "Dental", "Vision", "Pharmacy", or "Other"
- "amount": number or null if not visible
- "provider": string (provider or business name) or null if not visible
- "service_date": string in YYYY-MM-DD format for when the medical service was performed, \
or null if not determinable
- "payment_date": string in YYYY-MM-DD format for when the payment was made, \
or null if not determinable
- "reasoning": string explaining your determination

If the document contains only one transaction, still return a JSON array with one element.

Respond ONLY with the JSON array, no other text."""

ImageMediaType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
IMAGE_CONTENT_TYPES: frozenset[str] = frozenset(get_args(ImageMediaType))


@dataclass
class EligibilityResult:
    is_eligible: bool
    description: str
    short_description: str
    category: str
    amount: float | None
    provider: str | None
    service_date: str | None
    payment_date: str | None
    reasoning: str


def check_hsa_eligibility(api_key: str, attachment_data: bytes, content_type: str) -> list[EligibilityResult]:
    """Send a receipt to Claude and determine HSA eligibility.

    Returns a list of results — one per transaction found in the document.
    Supports both images and PDFs.
    """
    client = anthropic.Anthropic(api_key=api_key)

    data_b64 = base64.standard_b64encode(attachment_data).decode("ascii")

    content_block: ImageBlockParam | DocumentBlockParam
    if content_type in IMAGE_CONTENT_TYPES:
        content_block = ImageBlockParam(
            type="image",
            source=Base64ImageSourceParam(
                type="base64",
                media_type=cast(ImageMediaType, content_type),
                data=data_b64,
            ),
        )
    else:
        content_block = DocumentBlockParam(
            type="document",
            source=Base64PDFSourceParam(type="base64", media_type="application/pdf", data=data_b64),
        )

    prompt = TextBlockParam(
        type="text",
        text="Please analyze this receipt or statement for HSA eligibility."
        " Extract each out-of-pocket transaction separately.",
    )

    logger.info("Calling Claude API: content_type=%s, data_size=%d bytes", content_type, len(attachment_data))

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [content_block, prompt]}],
    )

    logger.info("Claude API returned: stop_reason=%s, content_blocks=%d", response.stop_reason, len(response.content))

    response_text = ""
    for block in response.content:
        if isinstance(block, TextBlock):
            response_text = block.text
            break

    logger.info("Claude response: %s", response_text)

    if not response_text.strip():
        logger.error("Claude returned empty response. Stop reason: %s", response.stop_reason)
        raise ValueError("Claude returned an empty response")

    # Strip markdown code fences if present
    stripped = response_text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [line for line in lines[1:] if line.strip() != "```"]
        stripped = "\n".join(lines)

    items: list[dict[str, object]] = json.loads(stripped)

    results: list[EligibilityResult] = []
    for item in items:
        amount = item.get("amount")
        provider = item.get("provider")
        service_date = item.get("service_date")
        payment_date = item.get("payment_date")
        is_eligible = item["is_eligible"]
        reasoning = str(item["reasoning"])

        if amount is None or provider is None or (service_date is None and payment_date is None):
            is_eligible = False
            reasoning += " Additionally, required fields (amount, provider, or date) could not be determined."

        results.append(
            EligibilityResult(
                is_eligible=bool(is_eligible),
                description=str(item["description"]),
                short_description=str(item["short_description"]),
                category=str(item.get("category", "Other")),
                amount=float(amount) if amount is not None else None,
                provider=str(provider) if provider is not None else None,
                service_date=str(service_date) if service_date is not None else None,
                payment_date=str(payment_date) if payment_date is not None else None,
                reasoning=reasoning,
            )
        )

    return results
