"""Dry run a receipt through Claude to see what it extracts, without storing anything."""

import argparse
import base64
import json
import mimetypes
import sys
from pathlib import Path

import anthropic

from hsa_receipt_archiver.claude_client import IMAGE_CONTENT_TYPES, SYSTEM_PROMPT

SUPPORTED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry run a receipt through Claude without storing anything.")
    parser.add_argument("file", type=Path, help="Receipt file (image or PDF)")
    parser.add_argument("--api-key", required=True, help="Anthropic API key")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001", help="Model to use (default: haiku)")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"Error: {args.file} is not a file", file=sys.stderr)
        sys.exit(1)

    content_type, _ = mimetypes.guess_type(str(args.file))
    if content_type not in SUPPORTED_CONTENT_TYPES:
        print(f"Error: unsupported file type {content_type}", file=sys.stderr)
        sys.exit(1)

    data = args.file.read_bytes()
    data_b64 = base64.standard_b64encode(data).decode("ascii")

    if content_type in IMAGE_CONTENT_TYPES:
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": content_type, "data": data_b64},
        }
    else:
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data_b64},
        }

    client = anthropic.Anthropic(api_key=args.api_key)
    print(f"Sending {args.file.name} to {args.model}...\n")

    response = client.messages.create(
        model=args.model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    content_block,
                    {"type": "text", "text": "Please analyze this receipt or statement for HSA eligibility."
                     " Extract each out-of-pocket transaction separately."},
                ],
            }
        ],
    )

    print(f"Stop reason: {response.stop_reason}")
    print(f"Input tokens: {response.usage.input_tokens}")
    print(f"Output tokens: {response.usage.output_tokens}\n")

    response_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            response_text = block.text
            break

    if response.stop_reason == "max_tokens":
        print("WARNING: Response was truncated (hit max_tokens)\n")

    try:
        items = json.loads(response_text)
        print(json.dumps(items, indent=2))
        print(f"\n{len(items)} transaction(s) found.")
    except json.JSONDecodeError:
        print("Raw response (failed to parse as JSON):\n")
        print(response_text)


if __name__ == "__main__":
    main()
