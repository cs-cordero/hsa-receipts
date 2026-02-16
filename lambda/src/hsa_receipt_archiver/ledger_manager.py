"""Manage the HSA receipt ledger (CSV file)."""

import csv
import io
from dataclasses import dataclass
from datetime import date

HEADERS = [
    "Service Date",
    "Payment Date",
    "Vendor/Provider",
    "Category",
    "Description",
    "Amount",
    "Receipt S3 URI",
    "Reimbursed",
    "Notes",
]


@dataclass
class LedgerEntry:
    service_date: date | None
    payment_date: date | None
    provider: str
    category: str
    description: str
    amount: float
    receipt_s3_uri: str


def create_empty_ledger() -> str:
    """Create a new empty CSV ledger with headers."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    return buf.getvalue()


def add_ledger_entry(ledger_csv: str | None, entry: LedgerEntry) -> str:
    """Add a new entry to the CSV ledger. Returns updated CSV string.

    If ledger_csv is None, creates a new ledger first.
    """
    if ledger_csv is None:
        ledger_csv = create_empty_ledger()

    buf = io.StringIO()
    buf.write(ledger_csv)
    if not ledger_csv.endswith("\n"):
        buf.write("\n")

    writer = csv.writer(buf)
    writer.writerow(
        [
            entry.service_date.isoformat() if entry.service_date else "",
            entry.payment_date.isoformat() if entry.payment_date else "",
            entry.provider,
            entry.category,
            entry.description,
            f"{entry.amount:.2f}",
            entry.receipt_s3_uri,
            "No",
            "",
        ]
    )

    return buf.getvalue()
