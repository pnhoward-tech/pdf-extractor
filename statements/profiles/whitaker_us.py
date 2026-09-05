"""Whitaker Bank Corporation of Kentucky — personal checking (USD).

**Partly derived.** The statement this was built from covers a month with no
activity at all — zero deposits, zero debits, opening balance equal to closing.
Its summary box is therefore validated; its transaction-line handling is not,
because the document contains no transaction lines to calibrate against.

Before trusting a batch on this profile, run one statement that *has*
transactions and read the reconciliation report. The column positions and the
`table_start` anchor below are read off the statement's printed structure and
are the parts most likely to need adjusting.

These statements arrive as scans with no text layer, so they need `--ocr`.
"""

from __future__ import annotations

import re
from datetime import date

from .base import Direction, Profile, TypeCode


def parse_slash_date(text: str) -> date:
    """MM/DD/YYYY or MM/DD/YY -> date. US month-first."""
    month, day, year = (int(part) for part in text.split("/"))
    if year < 100:
        year += 2000
    return date(year, month, day)


WHITAKER_US = Profile(
    name="whitaker-us",
    bank="Whitaker Bank Corporation of Kentucky",
    description="Whitaker Bank personal checking (USD) — transaction lines not yet validated",
    currency="USD",
    table_start=[
        re.compile(r"Deposits[-/]Other\s+Credits", re.I),
        re.compile(r"Checks/Other\s+Debits", re.I),
    ],
    table_stop=[
        re.compile(r"Daily\s+Ending\s+Bala", re.I),  # OCR renders "Balance" loosely
        re.compile(r"DIRECT\s+INQUIRIES\s+TO", re.I),
        re.compile(r"Total\s+Overdraft\s+Fees", re.I),
    ],
    summary_patterns={
        "opening_balance": re.compile(
            r"Beginning\s+Balance\s+([\d,]+\.\d{2})", re.I
        ),
        "closing_balance": re.compile(
            r"Ending\s+Balance\s+(?:\d+\s+Days\s+in\s+Statement\s+Period\s+)?([\d,]+\.\d{2})",
            re.I,
        ),
        "printed_paid_in": re.compile(
            r"Deposits[-/]Other\s+Credits\s*\+?\s*([\d,]*\.\d{2})", re.I
        ),
        "printed_paid_out": re.compile(
            r"Checks/Other\s+Debits\s*-?\s*([\d,]*\.\d{2})", re.I
        ),
    },
    period_pattern=re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+Beginning\s+Balance.*?(\d{2}/\d{2}/\d{4})\s+Ending\s+Balance",
        re.I | re.S,
    ),
    account_pattern=re.compile(r"\b(\d{8})\b"),
    page_pattern=re.compile(r"Pg\s+(\d+)\s+of\s+(\d+)", re.I),
    sheet_pattern=None,
    date_pattern=re.compile(r"^\s*(\d{2}/\d{2})\s"),
    parse_date=None,  # set below: these lines carry MM/DD without a year
    code_source="description_prefix",
    codes=(
        TypeCode("DEPOSIT", Direction.IN, "Deposit"),
        TypeCode("CHECK", Direction.OUT, "Cheque paid"),
        TypeCode("ATM WITHDRAWAL", Direction.OUT, "ATM withdrawal"),
        TypeCode("WITHDRAWAL", Direction.OUT, "Withdrawal"),
        TypeCode("SERVICE CHARGE", Direction.OUT, "Fee"),
        TypeCode("OVERDRAFT FEE", Direction.OUT, "Fee"),
        TypeCode("INTEREST", Direction.IN, "Interest"),
        TypeCode("POS", Direction.AMBIGUOUS, "Card"),
        TypeCode("ACH", Direction.AMBIGUOUS, "ACH"),
        TypeCode("TRANSFER", Direction.AMBIGUOUS, "Transfer"),
    ),
    balance_marker="none",
    paid_in_side="left",
    description_max_col=40,
    amount_band_width=45,
    default_in_out_split=110,
    balance_min_col=999,
    checkpoint_patterns=[
        re.compile(r"Beginning\s+Balance", re.I),
        re.compile(r"Ending\s+Balance", re.I),
    ],
    noise_patterns=[
        re.compile(r"^\s*Pg\s+\d+\s+of\s+\d+\s*$", re.I),
        re.compile(r"^[*#\-\s]+$"),
        re.compile(r"Total\s+(Overdraft|Returned)", re.I),
        re.compile(r"Year-to-Date", re.I),
        # The summary box sits inside the region the table anchor opens.
        re.compile(r"(Beginning|Ending)\s+Balance", re.I),
        re.compile(r"Deposits[-/]Other\s+Credits", re.I),
        re.compile(r"Checks/Other\s+Debits", re.I),
        re.compile(r"Days\s+in\s+Statement\s+Period", re.I),
    ],
)
WHITAKER_US.parse_date = staticmethod(parse_slash_date)
