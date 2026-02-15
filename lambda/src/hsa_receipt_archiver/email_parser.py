"""Parse incoming SES emails and extract attachments."""

from dataclasses import dataclass


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
    raise NotImplementedError
