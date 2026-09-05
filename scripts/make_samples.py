#!/usr/bin/env python3
"""Generate the synthetic PDFs in samples/ so the app can be tried without real data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.conftest import build_pdf  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

DOCS = {
    "invoice_acme.pdf": (
        "Invoice INV-2041 — ACME Supplies",
        "Invoice for professional services. Total due on receipt.",
        [
            ["Item", "Qty", "Unit Price", "Line Total"],
            ["Consulting services", "12", "$150.00", "$1,800.00"],
            ["Travel expenses", "1", "$420.50", "$420.50"],
            ["Software licence", "3", "$99.00", "$297.00"],
        ],
    ),
    "invoice_northwind.pdf": (
        "Invoice 7781 — Northwind Studio",
        "Invoice issued under contract. Total payable within 30 days.",
        [
            ["Description of Work", "Units", "Rate", "Amount (USD)"],
            ["Design retainer", "1", "2,500.00", "2,500.00"],
            ["Additional revisions", "4", "180.00", "720.00"],
            ["Print production", "2", "1.234,56", "2.469,12"],
        ],
    ),
    "statement_march.pdf": (
        "Account Statement — March 2024",
        "Statement of account covering March 2024. Closing balance shown below.",
        [
            ["Transaction Date", "Details", "Money Out", "Money In", "Balance"],
            ["01/03/2024", "Opening balance", "", "", "1,000.00"],
            ["03/03/2024", "Card payment - ACME", "45.20", "", "954.80"],
            ["07/03/2024", "Salary", "", "2,300.00", "3,254.80"],
            ["19/03/2024", "Rent", "1,200.00", "", "2,054.80"],
        ],
    ),
    "survey_readings.pdf": (
        "Site Survey — Sensor Readings",
        "Field readings taken during the March site visit.",
        [
            ["Sensor ID", "Reading", "Calibrated By"],
            ["S-01", "17.4", "PH"],
            ["S-02", "18.9", "PH"],
            ["S-03", "16.2", "RM"],
        ],
    ),
}


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    for name, (title, intro, rows) in DOCS.items():
        (SAMPLES / name).write_bytes(build_pdf(title, rows, intro=intro))
        print(f"wrote samples/{name}")


if __name__ == "__main__":
    main()
