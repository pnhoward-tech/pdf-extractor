"""Synthetic PDFs so the test suite doesn't depend on real documents."""

from __future__ import annotations

import io

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

RULED = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
)


def build_pdf(title: str, rows: list[list[str]], intro: str = "") -> bytes:
    """Render a heading, optional paragraph, and one ruled table into a PDF."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Heading1"])]
    if intro:
        story += [Paragraph(intro, styles["Normal"]), Spacer(1, 12)]
    table = Table(rows, repeatRows=1)
    table.setStyle(RULED)
    story.append(table)
    doc.build(story)
    return buffer.getvalue()


@pytest.fixture
def invoice_pdf() -> bytes:
    return build_pdf(
        "Invoice INV-2041",
        [
            ["Item", "Qty", "Unit Price", "Line Total"],
            ["Consulting services", "12", "$150.00", "$1,800.00"],
            ["Travel expenses", "1", "$420.50", "$420.50"],
            ["Software licence", "3", "$99.00", "$297.00"],
        ],
        intro="Invoice for professional services. Total due on receipt.",
    )


@pytest.fixture
def invoice_pdf_alt_headers() -> bytes:
    """Same data, different supplier's header wording."""
    return build_pdf(
        "Invoice 7781",
        [
            ["Description of Work", "Units", "Rate", "Amount (USD)"],
            ["Design retainer", "1", "2,500.00", "2,500.00"],
            ["Additional revisions", "4", "180.00", "720.00"],
        ],
        intro="Invoice issued under contract. Total payable within 30 days.",
    )


@pytest.fixture
def statement_pdf() -> bytes:
    return build_pdf(
        "Account Statement",
        [
            ["Transaction Date", "Details", "Money Out", "Money In", "Balance"],
            ["01/03/2024", "Opening balance", "", "", "1,000.00"],
            ["03/03/2024", "Card payment - ACME", "45.20", "", "954.80"],
            ["07/03/2024", "Salary", "", "2,300.00", "3,254.80"],
        ],
        intro="Statement of account covering March 2024. Closing balance shown below.",
    )


@pytest.fixture
def unknown_pdf() -> bytes:
    """A table that matches no profile, to exercise passthrough mode."""
    return build_pdf(
        "Site Survey",
        [
            ["Sensor ID", "Reading", "Calibrated By"],
            ["S-01", "17.4", "PH"],
            ["S-02", "18.9", "PH"],
        ],
    )


@pytest.fixture
def textless_pdf() -> bytes:
    """A valid PDF with no tables at all."""
    return build_pdf("Cover Letter", [["", ""], ["", ""]], intro="Please find enclosed.")
