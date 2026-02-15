"""Manage the HSA receipt ledger (Excel spreadsheet)."""

from dataclasses import dataclass
from datetime import date


@dataclass
class LedgerEntry:
    date: date
    provider: str
    description: str
    amount: float
    receipt_s3_uri: str


def add_ledger_entry(ledger_data: bytes, entry: LedgerEntry) -> bytes:
    """Add a new entry to the Excel ledger. Returns updated ledger bytes."""
    raise NotImplementedError


def create_empty_ledger() -> bytes:
    """Create a new empty Excel ledger with headers."""
    raise NotImplementedError
