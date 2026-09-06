"""S3 operations. They store a receipt, and they read and write the ledger."""

import re

import boto3
from botocore.exceptions import ClientError

_S3_CLIENT = boto3.client("s3")

_LEDGER_KEY = "ledger/hsa-receipts.csv"


def fetch_raw_email(bucket: str, key: str) -> bytes:
    """Fetch a raw email from S3."""
    response = _S3_CLIENT.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def store_receipt(bucket: str, pdf_data: bytes, receipt_date: str, provider: str, short_description: str) -> str:
    """Put a PDF/A receipt in S3. Return the S3 URI.

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

    _S3_CLIENT.put_object(Bucket=bucket, Key=receipt_key, Body=pdf_data, ContentType="application/pdf")
    return f"s3://{bucket}/{receipt_key}"


def fetch_ledger(bucket: str) -> str | None:
    """Get the CSV ledger from S3. Return None if no ledger exists yet."""
    try:
        response = _S3_CLIENT.get_object(Bucket=bucket, Key=_LEDGER_KEY)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise
    return response["Body"].read().decode("utf-8")


def store_ledger(bucket: str, ledger_data: str) -> None:
    """Upload the updated CSV ledger to S3."""
    _S3_CLIENT.put_object(
        Bucket=bucket,
        Key=_LEDGER_KEY,
        Body=ledger_data.encode("utf-8"),
        ContentType="text/csv",
    )


def store_upload(bucket: str, key: str, data: bytes, content_type: str) -> None:
    """Put an uploaded file in S3, under raw-uploads/."""
    _S3_CLIENT.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def fetch_upload(bucket: str, key: str) -> bytes:
    """Fetch an uploaded file from S3."""
    response = _S3_CLIENT.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def generate_presigned_receipt_url(bucket: str, key: str) -> str:
    """Make a presigned GET URL for a receipt PDF. The browser shows it in the page."""
    return _S3_CLIENT.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=300,
    )


def list_receipt_keys(bucket: str) -> list[str]:
    """Return every S3 key under the receipts/ prefix."""
    keys: list[str] = []
    paginator = _S3_CLIENT.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="receipts/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def delete_object(bucket: str, key: str) -> None:
    """Delete a single object from S3."""
    _S3_CLIENT.delete_object(Bucket=bucket, Key=key)


def tag_raw_email(bucket: str, key: str) -> None:
    """Mark a raw email as done. S3 then deletes it after 7 days, and not after 30."""
    _S3_CLIENT.put_object_tagging(
        Bucket=bucket,
        Key=key,
        Tagging={"TagSet": [{"Key": "status", "Value": "processed"}]},
    )


def _key_exists(bucket: str, key: str) -> bool:
    """Return True if this S3 key exists already."""
    try:
        _S3_CLIENT.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise
    return True


def _sanitize(text: str) -> str:
    """Make text safe for an S3 key. Each character that is not a letter or a digit becomes an underscore."""
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", text.strip())
    return sanitized.strip("_")
