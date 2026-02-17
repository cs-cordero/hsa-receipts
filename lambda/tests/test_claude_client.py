"""Tests for claude_client module."""

import json
from unittest.mock import MagicMock, patch

import pytest
from anthropic.types import TextBlock

from hsa_receipt_archiver.claude_client import check_hsa_eligibility


def _make_response(items: list[dict[str, object]] | None = None, text: str | None = None) -> MagicMock:
    """Build a mock Anthropic API response containing the given JSON items."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    text_block = MagicMock(spec=TextBlock)
    text_block.text = text if text is not None else json.dumps(items or [])
    mock_response.content = [text_block]
    return mock_response


def _single_eligible_item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "is_eligible": True,
        "description": "Office visit",
        "short_description": "Medical",
        "category": "Medical",
        "amount": 100.0,
        "provider": "Dr Smith",
        "service_date": "2025-01-15",
        "payment_date": "2025-01-16",
        "reasoning": "Standard medical expense",
    }
    base.update(overrides)
    return base


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_single_eligible_result(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response([_single_eligible_item()])

    results = check_hsa_eligibility("api-key", b"image-data", "image/jpeg")
    assert len(results) == 1
    assert results[0].is_eligible is True
    assert results[0].description == "Office visit"
    assert results[0].amount == 100.0


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_multiple_results(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    items = [
        _single_eligible_item(description="Visit 1", amount=50.0),
        _single_eligible_item(description="Visit 2", amount=75.0),
    ]
    mock_client.messages.create.return_value = _make_response(items)

    results = check_hsa_eligibility("api-key", b"data", "image/jpeg")
    assert len(results) == 2
    assert results[0].description == "Visit 1"
    assert results[1].description == "Visit 2"


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_missing_amount_forces_ineligible(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response([_single_eligible_item(amount=None)])

    results = check_hsa_eligibility("api-key", b"data", "image/jpeg")
    assert results[0].is_eligible is False
    assert "required fields" in results[0].reasoning.lower()


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_missing_provider_forces_ineligible(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response([_single_eligible_item(provider=None)])

    results = check_hsa_eligibility("api-key", b"data", "image/jpeg")
    assert results[0].is_eligible is False


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_both_dates_none_forces_ineligible(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response(
        [_single_eligible_item(service_date=None, payment_date=None)]
    )

    results = check_hsa_eligibility("api-key", b"data", "image/jpeg")
    assert results[0].is_eligible is False


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_one_date_present_stays_eligible(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response(
        [_single_eligible_item(service_date="2025-01-15", payment_date=None)]
    )

    results = check_hsa_eligibility("api-key", b"data", "image/jpeg")
    assert results[0].is_eligible is True


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_image_content_type_uses_image_block(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response([_single_eligible_item()])

    check_hsa_eligibility("api-key", b"data", "image/jpeg")
    call_kwargs = mock_client.messages.create.call_args[1]
    content = call_kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_pdf_content_type_uses_document_block(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response([_single_eligible_item()])

    check_hsa_eligibility("api-key", b"data", "application/pdf")
    call_kwargs = mock_client.messages.create.call_args[1]
    content = call_kwargs["messages"][0]["content"]
    assert content[0]["type"] == "document"


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_uses_correct_model(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response([_single_eligible_item()])

    check_hsa_eligibility("api-key", b"data", "image/jpeg")
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_passes_api_key(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response([_single_eligible_item()])

    check_hsa_eligibility("my-secret-key", b"data", "image/jpeg")
    mock_anthropic_cls.assert_called_once_with(api_key="my-secret-key")


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_empty_response_raises_value_error(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response(text="")

    with pytest.raises(ValueError, match="empty response"):
        check_hsa_eligibility("api-key", b"data", "image/jpeg")


@patch("hsa_receipt_archiver.claude_client.anthropic.Anthropic")
def test_markdown_fenced_json_is_parsed(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    fenced = "```json\n" + json.dumps([_single_eligible_item()]) + "\n```"
    mock_client.messages.create.return_value = _make_response(text=fenced)

    results = check_hsa_eligibility("api-key", b"data", "image/jpeg")
    assert len(results) == 1
    assert results[0].is_eligible is True
