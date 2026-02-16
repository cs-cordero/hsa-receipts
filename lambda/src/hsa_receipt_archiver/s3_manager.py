"""S3 operations for storing receipts and managing the ledger."""

import re

import boto3
from botocore.exceptions import ClientError

S3_CLIENT = boto3.client("s3")

LEDGER_KEY = "ledger/hsa-receipts.csv"


def fetch_raw_email(bucket: str, key: str) -> bytes:
    """Fetch a raw email from S3."""
    response = S3_CLIENT.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def store_receipt(bucket: str, pdf_data: bytes, receipt_date: str, provider: str, short_description: str) -> str:
    """Store a PDF/A receipt in S3. Returns the S3 URI.

    Naming: receipts/{year}/{date}_{provider}_{short_description}.pdf
    Appends _2, _3, etc. on collisions.
    """
    year = receipt_date[:4]
    provider_slug = _sanitize(provider)
    desc_slug = _sanitize(short_description)
    base_name = f"{receipt_date}_{provider_slug}_{desc_slug}"

    receipt_key = f"receipts/{year}/{base_name}.pdf"
    counter = 2
    while _key_exists(bucket, receipt_key):
        receipt_key = f"receipts/{year}/{base_name}_{counter}.pdf"
        counter += 1

    S3_CLIENT.put_object(Bucket=bucket, Key=receipt_key, Body=pdf_data, ContentType="application/pdf")
    return f"s3://{bucket}/{receipt_key}"


def fetch_ledger(bucket: str) -> str | None:
    """Fetch the CSV ledger from S3. Returns None if it doesn't exist yet."""
    try:
        response = S3_CLIENT.get_object(Bucket=bucket, Key=LEDGER_KEY)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise
    return response["Body"].read().decode("utf-8")


def store_ledger(bucket: str, ledger_data: str) -> None:
    """Upload the updated CSV ledger to S3."""
    S3_CLIENT.put_object(
        Bucket=bucket,
        Key=LEDGER_KEY,
        Body=ledger_data.encode("utf-8"),
        ContentType="text/csv",
    )


def tag_raw_email(bucket: str, key: str) -> None:
    """Tag a raw email as processed so it expires after 7 days instead of 30."""
    S3_CLIENT.put_object_tagging(
        Bucket=bucket,
        Key=key,
        Tagging={"TagSet": [{"Key": "status", "Value": "processed"}]},
    )


def _key_exists(bucket: str, key: str) -> bool:
    """Check if an S3 key already exists."""
    try:
        S3_CLIENT.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise
    return True


def _sanitize(text: str) -> str:
    """Sanitize text for use in an S3 key: replace non-alphanumeric with underscores."""
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", text.strip())
    return sanitized.strip("_")
