import csv
import io

from app.pipeline import META_COLUMNS, process_batch


def test_invoice_maps_to_profile_columns(invoice_pdf):
    result = process_batch([("inv.pdf", invoice_pdf)])
    assert result.row_count == 3
    row = result.rows[0]
    assert row["profile"] == "invoice"
    assert row["description"] == "Consulting services"
    assert row["quantity"] == "12"
    assert row["unit_price"] == "150"
    assert row["amount"] == "1800"


def test_different_suppliers_land_in_the_same_columns(invoice_pdf, invoice_pdf_alt_headers):
    result = process_batch([("a.pdf", invoice_pdf), ("b.pdf", invoice_pdf_alt_headers)])
    assert {r["profile"] for r in result.rows} == {"invoice"}
    assert all(r["amount"] for r in result.rows)
    assert [r["source_file"] for r in result.rows].count("b.pdf") == 2


def test_statement_dates_and_amounts_are_normalised(statement_pdf):
    result = process_batch([("stmt.pdf", statement_pdf)])
    rows = result.rows
    assert rows[0]["date"] == "2024-03-01"
    assert rows[1]["debit"] == "45.2"
    assert rows[2]["credit"] == "2300"
    assert rows[2]["balance"] == "3254.8"


def test_unmatched_tables_pass_through_with_their_own_headers(unknown_pdf):
    result = process_batch([("survey.pdf", unknown_pdf)])
    assert result.rows[0]["profile"] == "(raw headers)"
    assert result.rows[0]["Sensor ID"] == "S-01"
    assert "Reading" in result.columns


def test_unmatched_tables_can_be_excluded(unknown_pdf, invoice_pdf):
    result = process_batch(
        [("survey.pdf", unknown_pdf), ("inv.pdf", invoice_pdf)], include_unmatched=False
    )
    assert {r["source_file"] for r in result.rows} == {"inv.pdf"}


def test_forcing_a_profile_overrides_detection(unknown_pdf):
    result = process_batch([("survey.pdf", unknown_pdf)], forced_profile_name="invoice")
    assert result.rows[0]["profile"] == "invoice"
    assert result.columns[: len(META_COLUMNS)] == META_COLUMNS


def test_unreadable_file_is_reported_not_raised(invoice_pdf):
    result = process_batch([("broken.pdf", b"%PDF-1.4 not really"), ("ok.pdf", invoice_pdf)])
    broken = next(f for f in result.files if f.filename == "broken.pdf")
    assert broken.error
    assert result.row_count == 3  # the good file still came through


def test_csv_round_trips(invoice_pdf, statement_pdf):
    result = process_batch([("inv.pdf", invoice_pdf), ("stmt.pdf", statement_pdf)])
    parsed = list(csv.DictReader(io.StringIO(result.to_csv())))
    assert len(parsed) == result.row_count
    assert list(parsed[0].keys()) == result.columns
    assert {r["source_file"] for r in parsed} == {"inv.pdf", "stmt.pdf"}


def test_empty_columns_are_dropped_from_output(invoice_pdf):
    result = process_batch([("inv.pdf", invoice_pdf)])
    # The statement profile's columns never matched, so they must not appear.
    assert "balance" not in result.columns
