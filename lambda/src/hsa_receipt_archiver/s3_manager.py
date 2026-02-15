"""S3 operations for storing receipts and managing the ledger."""


def fetch_raw_email(bucket: str, key: str) -> bytes:
    """Fetch a raw email from S3."""
    raise NotImplementedError


def store_receipt(bucket: str, pdf_data: bytes, receipt_key: str) -> str:
    """Store a PDF/A receipt in S3. Returns the S3 URI."""
    raise NotImplementedError


def fetch_ledger(bucket: str, ledger_key: str) -> bytes:
    """Fetch the Excel ledger from S3."""
    raise NotImplementedError


def store_ledger(bucket: str, ledger_key: str, ledger_data: bytes) -> None:
    """Upload the updated Excel ledger to S3."""
    raise NotImplementedError
