"""Tests for ledger_manager module."""

import csv
import io
from datetime import date

from hsa_receipt_archiver.ledger_manager import HEADERS, LedgerEntry, add_ledger_entry, create_empty_ledger


def test_create_empty_ledger_has_headers() -> None:
    ledger = create_empty_ledger()
    reader = csv.reader(io.StringIO(ledger))
    headers = next(reader)
    assert headers == HEADERS


def test_create_empty_ledger_has_no_data_rows() -> None:
    ledger = create_empty_ledger()
    reader = csv.reader(io.StringIO(ledger))
    rows = list(reader)
    assert len(rows) == 1


def test_add_entry_to_none_creates_new_ledger(sample_ledger_entry: LedgerEntry) -> None:
    result = add_ledger_entry(None, sample_ledger_entry)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0] == HEADERS


def test_add_entry_appends_to_existing(sample_ledger_entry: LedgerEntry) -> None:
    ledger = create_empty_ledger()
    result = add_ledger_entry(ledger, sample_ledger_entry)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[1][2] == "Test Provider"
    assert rows[1][4] == "Office visit copay"


def test_add_entry_handles_missing_trailing_newline(sample_ledger_entry: LedgerEntry) -> None:
    ledger = create_empty_ledger().rstrip("\n")
    result = add_ledger_entry(ledger, sample_ledger_entry)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2


def test_add_entry_none_dates_become_empty_strings(ledger_entry_no_dates: LedgerEntry) -> None:
    result = add_ledger_entry(None, ledger_entry_no_dates)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    data_row = rows[1]
    assert data_row[0] == ""  # Service Date
    assert data_row[1] == ""  # Payment Date


def test_add_entry_formats_dates_as_iso(sample_ledger_entry: LedgerEntry) -> None:
    result = add_ledger_entry(None, sample_ledger_entry)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    data_row = rows[1]
    assert data_row[0] == "2025-01-15"
    assert data_row[1] == "2025-01-16"


def test_add_entry_formats_amount_two_decimals() -> None:
    entry = LedgerEntry(
        service_date=date(2025, 3, 1),
        payment_date=None,
        provider="P",
        category="Medical",
        description="D",
        amount=5.1,
        receipt_s3_uri="s3://b/r.pdf",
    )
    result = add_ledger_entry(None, entry)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert rows[1][5] == "5.10"


def test_add_entry_reimbursed_always_no(sample_ledger_entry: LedgerEntry) -> None:
    result = add_ledger_entry(None, sample_ledger_entry)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert rows[1][7] == "No"


def test_add_entry_notes_always_empty(sample_ledger_entry: LedgerEntry) -> None:
    result = add_ledger_entry(None, sample_ledger_entry)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert rows[1][8] == ""


def test_add_multiple_entries() -> None:
    entry1 = LedgerEntry(
        service_date=date(2025, 1, 1),
        payment_date=None,
        provider="A",
        category="Medical",
        description="First",
        amount=10.00,
        receipt_s3_uri="s3://b/1.pdf",
    )
    entry2 = LedgerEntry(
        service_date=date(2025, 2, 1),
        payment_date=None,
        provider="B",
        category="Dental",
        description="Second",
        amount=20.00,
        receipt_s3_uri="s3://b/2.pdf",
    )
    ledger = add_ledger_entry(None, entry1)
    ledger = add_ledger_entry(ledger, entry2)
    reader = csv.reader(io.StringIO(ledger))
    rows = list(reader)
    assert len(rows) == 3
    assert rows[1][4] == "First"
    assert rows[2][4] == "Second"
