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
    "Prob. of Duplicate",
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

    dupe_pct = _duplicate_score(ledger_csv, entry)

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
            f"{dupe_pct}" if dupe_pct > 0 else "",
        ]
    )

    return buf.getvalue()


def _duplicate_score(ledger_csv: str, entry: LedgerEntry) -> int:
    """Score how likely an entry is a duplicate of an existing row (0-100).

    Scoring:
    - Same provider (case-insensitive): +30
    - Same amount: +30
    - Same service date: +40 (exact match) or +20 (within 30 days)
    """
    reader = csv.DictReader(io.StringIO(ledger_csv))
    best = 0

    for row in reader:
        score = 0

        if row.get("Vendor/Provider", "").strip().lower() == entry.provider.strip().lower():
            score += 30

        try:
            row_amount = float(row.get("Amount", "0"))
        except ValueError:
            row_amount = 0.0
        if abs(row_amount - entry.amount) < 0.01:
            score += 30

        row_date_str = row.get("Service Date", "").strip()
        if row_date_str and entry.service_date:
            try:
                row_date = date.fromisoformat(row_date_str)
                if row_date == entry.service_date:
                    score += 40
                elif abs((row_date - entry.service_date).days) <= 30:
                    score += 20
            except ValueError:
                pass

        best = max(best, score)

    return best
