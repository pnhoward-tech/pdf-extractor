"""CSV schema, and the gate that keeps unreconciled statements out of it."""

import csv
from pathlib import Path

import pytest

from statements.cli import main
from statements.parse import parse_statement
from statements.profiles import get_profile
from statements.reconcile import reconcile
from statements.report import RECONCILIATION_COLUMNS, TRANSACTION_COLUMNS, transaction_rows
from tests.bank.fixtures import us_statement


@pytest.fixture
def rows():
    doc = parse_statement("stmt.pdf", get_profile("hsbc-us"), text=us_statement())
    reconcile(doc)
    return transaction_rows(doc, "CUR1")


def test_schema_is_exactly_the_agreed_columns(rows):
    assert list(rows[0].keys()) == TRANSACTION_COLUMNS


def test_dates_are_iso_so_uk_and_us_batches_can_be_mixed(rows):
    for row in rows:
        assert len(row["txn_date"]) == 10 and row["txn_date"][4] == "-"
        assert row["statement_period_start"] == "2025-01-07"


def test_paid_out_and_paid_in_are_mutually_exclusive(rows):
    for row in rows:
        assert not (row["paid_out"] and row["paid_in"])
        assert row["paid_out"] or row["paid_in"]


def test_amount_is_signed_positive_for_money_out(rows):
    purchase = next(r for r in rows if "FLAT WHITE" in r["description"])
    interest = next(r for r in rows if r["type_code"] == "INTEREST PAID")
    assert purchase["amount"] == "40.00" and purchase["paid_out"] == "40.00"
    assert interest["amount"] == "-0.04" and interest["paid_in"] == "0.04"


def test_account_label_and_currency_are_stamped_on_every_row(rows):
    assert {r["account_label"] for r in rows} == {"CUR1"}
    assert {r["currency"] for r in rows} == {"USD"}


def test_foreign_currency_detail_is_kept(rows):
    milano = next(r for r in rows if "CAFE MILANO" in r["description"])
    assert milano["foreign_amount"] == "45.00"
    assert milano["foreign_currency"] == "EUR"


# --------------------------------------------------------------------------- #
# CLI, end to end over the filesystem
# --------------------------------------------------------------------------- #

def write_pdf_stub(tmp_path: Path, name: str, text: str) -> Path:
    """A .txt sidecar the CLI can't read — used to prove PDF-less paths error
    cleanly rather than half-succeeding."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_lists_profiles(capsys):
    assert main(["profiles"]) == 0
    out = capsys.readouterr().out
    assert "hsbc-us" in out and "hsbc-uk" in out


def test_cli_rejects_an_unknown_profile(tmp_path, capsys):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    assert main(["extract", str(tmp_path), "-p", "nope", "-o", str(tmp_path / "o")]) == 1
    assert "unknown profile" in capsys.readouterr().err


def test_cli_reports_when_no_pdfs_found(tmp_path, capsys):
    assert main(["extract", str(tmp_path), "-p", "hsbc-us", "-o", str(tmp_path / "o")]) == 1
    assert "No PDFs found" in capsys.readouterr().err


def test_unreconciled_statement_is_held_back(monkeypatch, tmp_path, capsys):
    """A statement whose totals don't add up must not reach the transactions CSV."""
    from statements import batch, cli

    broken = us_statement().replace("$180.00", "$999.00")
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(batch, "parse_statement",
                        lambda pdf, profile, **kw: parse_statement(pdf, profile, text=broken))

    out_dir = tmp_path / "o"
    assert cli.main(["extract", str(tmp_path), "-p", "hsbc-us", "-o", str(out_dir)]) == 2

    transactions = list(csv.DictReader((out_dir / "transactions.csv").open()))
    assert transactions == []
    report = list(csv.DictReader((out_dir / "reconciliation.csv").open()))
    assert report[0]["check"] == "CHECK"
    assert list(report[0].keys()) == RECONCILIATION_COLUMNS
    assert "HELD BACK" in capsys.readouterr().out


def test_include_failed_ships_the_rows_with_a_warning(monkeypatch, tmp_path, capsys):
    from statements import batch, cli

    broken = us_statement().replace("$180.00", "$999.00")
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(batch, "parse_statement",
                        lambda pdf, profile, **kw: parse_statement(pdf, profile, text=broken))

    out_dir = tmp_path / "o"
    assert cli.main(["extract", str(tmp_path), "-p", "hsbc-us", "-o", str(out_dir), "--include-failed"]) == 2
    assert list(csv.DictReader((out_dir / "transactions.csv").open()))
    assert "WARNING: included rows" in capsys.readouterr().out


def test_clean_batch_exits_zero_and_writes_both_csvs(monkeypatch, tmp_path):
    from statements import batch, cli

    (tmp_path / "good.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(batch, "parse_statement",
                        lambda pdf, profile, **kw: parse_statement(pdf, profile, text=us_statement()))

    out_dir = tmp_path / "o"
    assert cli.main(["extract", str(tmp_path), "-p", "hsbc-us", "-a", "CUR1", "-o", str(out_dir)]) == 0
    transactions = list(csv.DictReader((out_dir / "transactions.csv").open()))
    assert len(transactions) == 5
    assert {r["account_label"] for r in transactions} == {"CUR1"}


def test_scanned_pdf_without_ocr_says_so_rather_than_yielding_nothing(tmp_path, monkeypatch):
    """A scan must not look like a statement with no transactions."""
    from statements import parse as parse_module

    monkeypatch.setattr(parse_module, "has_text_layer", lambda pdf: False, raising=False)
    monkeypatch.setattr("statements.ocr.has_text_layer", lambda pdf: False)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    doc = parse_statement(pdf, get_profile("hsbc-us"))
    assert doc.transactions == []
    assert any("no text layer" in w and "--ocr" in w for w in doc.warnings)


AGREED_SCHEMA = [
    "source_file", "account_label", "page_number", "sheet_number",
    "statement_period_start", "statement_period_end", "txn_date", "type_code",
    "description", "paid_out", "paid_in", "amount", "currency", "foreign_amount",
    "foreign_currency", "running_balance", "direction_confidence", "reconciliation_note",
]


def test_agreed_schema_comes_first_and_unchanged():
    """Later additions are appended, so a loader reading by name or by position
    up to `reconciliation_note` keeps working."""
    assert TRANSACTION_COLUMNS[: len(AGREED_SCHEMA)] == AGREED_SCHEMA


def test_added_columns_carry_source_owner_and_duplicate_tags():
    for column in ("posting_date", "source_account", "owner", "duplicate_group",
                   "duplicate_of", "date_confidence"):
        assert column in TRANSACTION_COLUMNS
