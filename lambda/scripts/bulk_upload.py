"""Bulk upload receipt files through the deployed Lambda pipeline.

Replicates what SES does: wraps each file in a MIME email, uploads to S3
as raw-emails/{id}, and invokes the Lambda with a synthetic SES event.
"""

import argparse
import json
import mimetypes
import shutil
import sys
import time
import uuid
from email.message import EmailMessage
from pathlib import Path

import boto3

SUPPORTED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
}

LAMBDA_FUNCTION_NAME = "hsa-receipt-archiver"
RECIPIENT = "receipts@hsa.corderohq.com"


def build_mime_email(sender: str, filename: str, content_type: str, data: bytes) -> bytes:
    """Construct a MIME email with the receipt file as an attachment."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = RECIPIENT
    msg["Subject"] = filename
    msg.set_content("Bulk upload receipt.")

    maintype, subtype = content_type.split("/")
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    return msg.as_bytes()


def upload_and_invoke(
    s3_client: "boto3.client",
    lambda_client: "boto3.client",
    bucket: str,
    mime_bytes: bytes,
) -> dict:
    """Upload MIME email to S3 and invoke the Lambda."""
    message_id = str(uuid.uuid4())
    s3_key = f"raw-emails/{message_id}"

    s3_client.put_object(Bucket=bucket, Key=s3_key, Body=mime_bytes)

    event = {
        "Records": [
            {
                "ses": {
                    "mail": {"messageId": message_id},
                    "receipt": {
                        "spfVerdict": {"status": "PASS"},
                        "dkimVerdict": {"status": "PASS"},
                        "dmarcVerdict": {"status": "PASS"},
                    },
                }
            }
        ]
    }
    response = lambda_client.invoke(
        FunctionName=LAMBDA_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )

    payload = json.loads(response["Payload"].read())
    return payload


def collect_receipt_files(directory: Path) -> list[Path]:
    """Collect supported receipt files from a directory, sorted by name."""
    files = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        content_type, _ = mimetypes.guess_type(str(path))
        if content_type in SUPPORTED_CONTENT_TYPES:
            files.append(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk upload receipts through the Lambda pipeline.")
    parser.add_argument("directory", type=Path, help="Directory containing receipt files")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--sender", required=True, help="Allowed sender email address")
    parser.add_argument("--failures-dir", required=True, type=Path, help="Directory to copy failed files into")
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    args.failures_dir.mkdir(parents=True, exist_ok=True)

    files = collect_receipt_files(args.directory)
    if not files:
        print(f"No supported receipt files found in {args.directory}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(files)} receipt(s) to upload.\n")

    s3_client = boto3.client("s3")
    lambda_client = boto3.client("lambda")

    failures = 0
    for i, path in enumerate(files, 1):
        content_type, _ = mimetypes.guess_type(str(path))
        data = path.read_bytes()
        mime_bytes = build_mime_email(args.sender, path.name, content_type, data)

        print(f"[{i}/{len(files)}] {path.name}...", end=" ", flush=True)
        try:
            result = upload_and_invoke(s3_client, lambda_client, args.bucket, mime_bytes)
            status = result.get("statusCode", "???")
            if status == 200:
                print(f"OK ({status})")
            else:
                print(f"FAILED ({status}): {result.get('body', '')}")
                shutil.copy2(path, args.failures_dir / path.name)
                failures += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            shutil.copy2(path, args.failures_dir / path.name)
            failures += 1

        if i < len(files):
            time.sleep(10)

    print(f"\nDone. {len(files) - failures}/{len(files)} succeeded.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
