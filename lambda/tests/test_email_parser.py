"""Tests for email_parser module."""

from collections.abc import Callable

from hsa_receipt_archiver.email_parser import parse_ses_email


def test_parse_simple_text_email(make_mime_email: Callable[..., bytes]) -> None:
    raw = make_mime_email(body="Hello world")
    parsed = parse_ses_email(raw)
    assert parsed.body.strip() == "Hello world"
    assert parsed.attachments == []


def test_parse_email_extracts_sender_and_subject(make_mime_email: Callable[..., bytes]) -> None:
    raw = make_mime_email(sender="alice@example.com", subject="My Receipt")
    parsed = parse_ses_email(raw)
    assert "alice@example.com" in parsed.sender
    assert parsed.subject == "My Receipt"


def test_parse_email_with_jpeg_attachment(make_mime_email: Callable[..., bytes]) -> None:
    raw = make_mime_email(attachments=[("photo.jpg", "image/jpeg", b"jpeg-data")])
    parsed = parse_ses_email(raw)
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].content_type == "image/jpeg"
    assert parsed.attachments[0].filename == "photo.jpg"
    assert parsed.attachments[0].data == b"jpeg-data"


def test_parse_email_with_pdf_attachment(make_mime_email: Callable[..., bytes]) -> None:
    raw = make_mime_email(attachments=[("receipt.pdf", "application/pdf", b"pdf-data")])
    parsed = parse_ses_email(raw)
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].content_type == "application/pdf"


def test_parse_email_with_multiple_attachments(make_mime_email: Callable[..., bytes]) -> None:
    raw = make_mime_email(
        attachments=[
            ("photo.jpg", "image/jpeg", b"jpeg-data"),
            ("doc.pdf", "application/pdf", b"pdf-data"),
            ("scan.png", "image/png", b"png-data"),
        ]
    )
    parsed = parse_ses_email(raw)
    assert len(parsed.attachments) == 3
    content_types = {a.content_type for a in parsed.attachments}
    assert content_types == {"image/jpeg", "application/pdf", "image/png"}


def test_parse_email_ignores_unsupported_content_types(make_mime_email: Callable[..., bytes]) -> None:
    raw = make_mime_email(
        attachments=[
            ("archive.zip", "application/zip", b"zip-data"),
            ("photo.jpg", "image/jpeg", b"jpeg-data"),
        ]
    )
    parsed = parse_ses_email(raw)
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].content_type == "image/jpeg"


def test_parse_email_body_not_overwritten_by_attachment(make_mime_email: Callable[..., bytes]) -> None:
    raw = make_mime_email(
        body="Original body",
        attachments=[("photo.jpg", "image/jpeg", b"jpeg-data")],
    )
    parsed = parse_ses_email(raw)
    assert parsed.body.strip() == "Original body"
    assert len(parsed.attachments) == 1


def test_parse_email_missing_headers() -> None:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg.set_content("body")
    raw = msg.as_bytes()
    parsed = parse_ses_email(raw)
    assert parsed.sender == ""
    assert parsed.subject == ""
    assert parsed.body.strip() == "body"
