"""HSBC UK — Premier / current account, sterling.

Built from the written reference profile rather than from statements in hand,
so treat its column numbers as a starting point: run a couple of statements
through and read the reconciliation report before trusting a batch. The
balance-delta validation in `reconcile.py` is what catches a wrong guess here.

Notable differences from the US layout:

* A real type-code column, read as the first token after any leading date.
* Sterling dates, DD Mon YY.
* Paid-out / paid-in / balance sit in fixed horizontal bands, and the balance
  carries no currency symbol, so the band is what identifies it.
* BP, VIS, SO, DR and contactless ")))" each post on either side in practice —
  a refund reuses the purchase code — so they are ambiguous by design.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .base import Direction, Profile, TypeCode


def parse_uk_date(text: str) -> date:
    """'05 Jan 25' -> date. Day-first, never month-first."""
    cleaned = " ".join(text.split())
    for fmt in ("%d %b %y", "%d %b %Y", "%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised UK date: {text!r}")


HSBC_UK_PREMIER = Profile(
    name="hsbc-uk",
    bank="HSBC UK",
    description="HSBC UK Premier / current account (GBP) — profile not yet validated",
    currency="GBP",
    # Anchored loosely: the header's spacing varies page to page.
    table_start=[re.compile(r"^\s*Date\s+Pay", re.I)],
    table_continues=[re.compile(r"BALANCE BROUGHT FORWARD", re.I)],
    table_stop=[
        re.compile(r"Information about the Financial Services Compensation Scheme", re.I),
        re.compile(r"^\s*Interest rate", re.I),
        re.compile(r"AER\b.*\bGross\b", re.I),
    ],
    summary_patterns={
        "opening_balance": re.compile(r"Opening Balance\s+([\d,]+\.\d{2})", re.I),
        "closing_balance": re.compile(r"Closing Balance\s+([\d,]+\.\d{2})", re.I),
        "printed_paid_in": re.compile(r"(?:Payments|Total Paid) In\s+([\d,]+\.\d{2})", re.I),
        "printed_paid_out": re.compile(r"(?:Payments|Total Paid) Out\s+([\d,]+\.\d{2})", re.I),
    },
    period_pattern=re.compile(
        r"(\d{1,2}\s+\w{3,9}\s+\d{2,4})\s+to\s+(\d{1,2}\s+\w{3,9}\s+\d{2,4})", re.I
    ),
    account_pattern=re.compile(r"Account Number\s+([\d\s\-]+)", re.I),
    sheet_pattern=re.compile(r"Sheet(?:\s+Number)?\s+(\d+)", re.I),
    page_pattern=re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I),
    date_pattern=re.compile(r"^\s*(\d{1,2}\s+\w{3}\s+\d{2})\s"),
    parse_date=parse_uk_date,
    code_source="first_token",
    codes=(
        TypeCode("DD", Direction.OUT, "Direct debit"),
        TypeCode("ATM", Direction.OUT, "Cash machine"),
        TypeCode("OBP", Direction.OUT, "Online bill payment"),
        TypeCode("CR", Direction.IN, "Credit"),
        # Each of these has been seen on both sides.
        TypeCode("BP", Direction.AMBIGUOUS, "Bill payment"),
        TypeCode("VIS", Direction.AMBIGUOUS, "Visa card"),
        TypeCode("SO", Direction.AMBIGUOUS, "Standing order"),
        TypeCode("DR", Direction.AMBIGUOUS, "Debit"),
        TypeCode(")))", Direction.AMBIGUOUS, "Contactless"),
    ),
    balance_marker="column",
    # Below this column, numbers are description content: foreign-currency
    # amounts, exchange rates, long reference numbers.
    description_max_col=46,
    # Balance ~121, paid-in ~96, paid-out ~71 -> a 50-character band, plus margin.
    amount_band_width=58,
    paid_in_side="right",  # "Paid out" sits left of "Paid in"
    default_in_out_split=80,
    balance_min_col=105,
    checkpoint_patterns=[re.compile(r"BALANCE (BROUGHT|CARRIED) FORWARD", re.I)],
    noise_patterns=[
        re.compile(r"^\s*Page \d+ of \d+\s*$", re.I),
        re.compile(r"^\s*Date\s+Payment type", re.I),
    ],
)
