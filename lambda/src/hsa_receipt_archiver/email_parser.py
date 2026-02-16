"""Parse incoming SES emails and extract attachments."""

import email
import email.policy
from dataclasses import dataclass

SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "application/pdf",
    }
)


@dataclass
class ParsedEmail:
    sender: str
    subject: str
    body: str
    attachments: list["Attachment"]


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


def parse_ses_email(raw_email: bytes) -> ParsedEmail:
    """Parse a raw email from S3 into structured data."""
    msg = email.message_from_bytes(raw_email, policy=email.policy.default)

    sender = str(msg.get("From", ""))
    subject = str(msg.get("Subject", ""))

    body = ""
    attachments: list[Attachment] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))

        if content_type == "text/plain" and "attachment" not in disposition:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                body = payload.decode("utf-8", errors="replace")
        elif content_type in SUPPORTED_CONTENT_TYPES:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                filename = part.get_filename() or f"attachment.{content_type.split('/')[-1]}"
                attachments.append(Attachment(filename=filename, content_type=content_type, data=payload))

    return ParsedEmail(sender=sender, subject=subject, body=body, attachments=attachments)
