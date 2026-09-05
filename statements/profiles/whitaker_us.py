"""Whitaker Bank Corporation of Kentucky — personal checking (USD).

These statements arrive as scans with no text layer, so they need `--ocr`.

The distinctive feature is that **direction comes from a section heading**, not
from a column or a code: everything under "Deposits/Other Credits" is money in,
everything under "Other Debits" is money out. There is one amount column and no
running balance beside transactions, so the statement-level check is what
validates.

OCR mangles the dashed section dividers ("Sons c css snc csc sccscncccn------
Other Debits ---------"), so the section patterns match only the words that
survive, anchored on the run of dashes that distinguishes a divider from the
summary line above it — which repeats the same words next to a total.
"""

from __future__ import annotations

import re
from datetime import date

from .base import Direction, Profile, TypeCode

DASHES = r"-{3,}"


def parse_slash_date(text: str) -> date:
    """MM/DD/YYYY or MM/DD/YY -> date. US month-first."""
    month, day, year = (int(part) for part in text.split("/"))
    if year < 100:
        year += 2000
    return date(year, month, day)


WHITAKER_US = Profile(
    name="whitaker-us",
    bank="Whitaker Bank Corporation of Kentucky",
    description="Whitaker Bank personal checking (USD), scanned",
    currency="USD",
    # The divider is also what sets the first section's direction, so the
    # region has to include the line that matched.
    table_start=[re.compile(DASHES + r".*Deposits.*Credits", re.I)],
    table_start_offset=0,
    table_stop=[
        re.compile(DASHES + r".*Daily\s+Ending\s+Bala", re.I),
        re.compile(r"DIRECT\s+INQUIRIES\s+TO", re.I),
        re.compile(r"IN\s+CASE\s+OF\s+ERRORS", re.I),
    ],
    section_patterns=[
        (re.compile(DASHES + r".*Deposits.*Credits", re.I), Direction.IN),
        (re.compile(DASHES + r".*Other\s+Debits", re.I), Direction.OUT),
    ],
    summary_patterns={
        "opening_balance": re.compile(r"Beginning\s+Balance\s+([\d,]*\.\d{2})", re.I),
        "closing_balance": re.compile(
            r"Ending\s+Balance\s+(?:\d+\s+Days\s+in\s+Statement\s+Period\s+)?([\d,]*\.\d{2})",
            re.I,
        ),
        "printed_paid_in": re.compile(
            r"Deposits[-/][“\"']?Other\s+Credits\s*\+?\s*([\d,]*\.\d{2})", re.I
        ),
        "printed_paid_out": re.compile(
            r"Checks/[“\"']?Other\s+Debits\s*-?\s*([\d,]*\.\d{2})", re.I
        ),
    },
    period_pattern=re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+Beginning\s+Balance.*?(\d{2}/\d{2}/\d{4})\s+Ending\s+Balance",
        re.I | re.S,
    ),
    account_pattern=re.compile(r"\b(\d{8})\b"),
    # The account holder is the capitalised line directly above the street
    # address, which is what distinguishes it from the account-type line.
    owner_pattern=re.compile(
        r"^\s*([A-Z][A-Z0-9\s.'&]{4,40}?)\s*\n\s*\d+\s+[A-Z]", re.M
    ),
    page_pattern=re.compile(r"Pg\s+(\d+)\s+of\s+(\d+)", re.I),
    sheet_pattern=None,
    date_pattern=re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s"),
    parse_date=parse_slash_date,
    date_starts_transaction=True,
    code_source="description_prefix",
    codes=(
        TypeCode("WIRE DEPOSIT", Direction.IN, "Wire in"),
        TypeCode("WIRE FEE", Direction.OUT, "Wire fee"),
        TypeCode("ACH PAYMENT", Direction.OUT, "ACH payment"),
        TypeCode("ACH DEPOSIT", Direction.IN, "ACH deposit"),
        TypeCode("DEPOSIT", Direction.IN, "Deposit"),
        TypeCode("CHECK", Direction.OUT, "Cheque paid"),
        TypeCode("ATM WITHDRAWAL", Direction.OUT, "ATM withdrawal"),
        TypeCode("WITHDRAWAL", Direction.OUT, "Withdrawal"),
        TypeCode("SERVICE CHARGE", Direction.OUT, "Fee"),
        TypeCode("OVERDRAFT FEE", Direction.OUT, "Fee"),
        TypeCode("INTEREST", Direction.IN, "Interest"),
        TypeCode("POS", Direction.AMBIGUOUS, "Card"),
        TypeCode("TRANSFER", Direction.AMBIGUOUS, "Transfer"),
    ),
    default_code="TXN",
    balance_marker="none",
    description_max_col=40,
    amount_band_width=40,
    default_in_out_split=110,
    balance_min_col=999,
    checkpoint_patterns=[],
    noise_patterns=[
        re.compile(r"^\s*Pg\s+\d+\s+of\s+\d+\s*$", re.I),
        re.compile(r"^[*#\-\s|]+$"),
        # The fee table at the foot of the page is drawn with pipe characters.
        re.compile(r"^\s*\|"),
        re.compile(r"Total\s+(Overdraft|Returned)", re.I),
        re.compile(r"Year-to-Date", re.I),
        re.compile(r"(Beginning|Ending)\s+Balance", re.I),
        re.compile(r"Days\s+in\s+Statement\s+Period", re.I),
    ],
)
