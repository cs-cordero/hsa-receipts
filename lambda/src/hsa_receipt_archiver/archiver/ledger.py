"""Manage the HSA receipt ledger (CSV file)."""

import csv
import io
from dataclasses import dataclass
from datetime import date

from hsa_receipt_archiver.util import today

_HEADERS = [
    "Id",
    "Service Date",
    "Payment Date",
    "Vendor/Provider",
    "Patient/For",
    "Category",
    "Description",
    "Amount",
    "Receipt S3 URI",
    "Reimbursed",
    "Creation Date",
    "Notes",
    "Prob. of Duplicate",
]


@dataclass
class LedgerEntry:
    service_date: date | None
    payment_date: date | None
    provider: str
    patient: str
    category: str
    description: str
    amount: float
    receipt_s3_uri: str


def normalize_line_endings(text: str) -> str:
    """Normalize all line endings (\\r\\n, \\r) to \\n."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def create_empty_ledger() -> str:
    """Create a new empty CSV ledger with headers."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_HEADERS)
    return buf.getvalue()


def add_ledger_entry(ledger_csv: str | None, entry: LedgerEntry) -> str:
    """Add a new entry to the CSV ledger. Returns updated CSV string.

    If ledger_csv is None, creates a new ledger first.
    """
    if ledger_csv is None:
        ledger_csv = create_empty_ledger()

    ledger_csv = normalize_line_endings(ledger_csv)
    dupe_pct = _duplicate_score(ledger_csv, entry)
    next_id = _next_id(ledger_csv)

    buf = io.StringIO()
    buf.write(ledger_csv)
    if not ledger_csv.endswith("\n"):
        buf.write("\n")

    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            next_id,
            entry.service_date.isoformat() if entry.service_date else "",
            entry.payment_date.isoformat() if entry.payment_date else "",
            entry.provider,
            entry.patient,
            entry.category,
            entry.description,
            f"{entry.amount:.2f}",
            entry.receipt_s3_uri,
            "No",
            today().isoformat(),
            "",
            f"{dupe_pct}" if dupe_pct > 0 else "",
        ]
    )

    return buf.getvalue()


def _next_id(ledger_csv: str) -> int:
    """Return the next Id value (max existing Id + 1, or 1 if no rows)."""
    reader = csv.DictReader(io.StringIO(ledger_csv))
    max_id = 0
    for row in reader:
        try:
            max_id = max(max_id, int(row.get("Id", "0")))
        except ValueError:
            pass
    return max_id + 1


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
