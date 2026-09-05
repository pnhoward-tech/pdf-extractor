"""HSBC Bank USA, N.A. — Premier / personal checking, US dollar.

Derived from real statements (Rev. 1/2022 layout). Distinctive features versus
the UK layout:

* No type-code column. Transactions are classified on their description prefix
  ("PURCHASE ON ...", "INTEREST PAID FROM ...").
* Dates are US month-first, MM/DD/YY, and carry forward across lines.
* The running balance is printed against every transaction and is the only
  amount carrying a `$`, which identifies it far more reliably than its column.
* Column positions shift between the first page (which carries the summary box)
  and continuation pages — amounts end near column 119/140 on page 1 but near
  97/118 afterwards, so nothing here may hardcode a single threshold.
"""

from __future__ import annotations

import re
from datetime import date

from .base import Direction, Profile, TypeCode


def parse_us_date(text: str) -> date:
    """MM/DD/YY -> date. Two-digit years are 2000-2099."""
    month, day, year = (int(part) for part in text.split("/"))
    return date(2000 + year if year < 100 else year, month, day)


HSBC_US_PREMIER = Profile(
    name="hsbc-us",
    bank="HSBC Bank USA, N.A.",
    description="HSBC US Premier / personal checking (USD)",
    currency="USD",
    table_start=[re.compile(r"^POSTED\s+DESCRIPTION\s+OF\s+TRANSACTIONS", re.I)],
    table_continues=[re.compile(r"CONTINUED\s+FROM\s+PREVIOUS\s+PAGE", re.I)],
    table_stop=[
        re.compile(r"All deposited items are credited subject to final payment", re.I),
        re.compile(r"For Consumer Accounts Only", re.I),
        re.compile(r"IN CASE OF ERRORS OR QUESTIONS", re.I),
        re.compile(r"Some of the payment information provided herein", re.I),
        re.compile(r"Please examine your statement at once", re.I),
    ],
    summary_patterns={
        "opening_balance": re.compile(r"^BEGINNING BALANCE\s+\$?([\d,]+\.\d{2})", re.I | re.M),
        "closing_balance": re.compile(r"^ENDING BALANCE\s+\$?([\d,]+\.\d{2})", re.I | re.M),
        "printed_paid_in": re.compile(
            r"^\s*DEPOSITS & OTHER ADDITIONS\s+\$?([\d,]+\.\d{2})", re.I | re.M
        ),
        "printed_paid_out": re.compile(
            r"^\s*WITHDRAWALS & OTHER SUBTRACTIONS\s+\$?([\d,]+\.\d{2})", re.I | re.M
        ),
    },
    period_pattern=re.compile(
        r"STATEMENT PERIOD\s+(\d{2}/\d{2}/\d{2})\s+TO\s+(\d{2}/\d{2}/\d{2})", re.I
    ),
    account_pattern=re.compile(r"ACCOUNT NUMBER\s+([\d\-]+)", re.I),
    # The holders are restated on their own short lines just above the
    # transaction table — cleaner than the address block, which sits beside
    # the bank's own contact details.
    owner_pattern=re.compile(
        r"^\s{1,4}([A-Z][A-Z.'\- ]{4,34})\s*$\n(?:^\s{1,4}([A-Z][A-Z.'\- ]{4,34})\s*$\n)?"
        r"(?=\s*$|\s*[A-Z ]*DATE)",
        re.M,
    ),
    page_pattern=re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I),
    sheet_pattern=None,  # HSBC US prints no cross-statement sheet number
    date_pattern=re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s"),
    parse_date=parse_us_date,
    code_source="description_prefix",
    codes=(
        # Unambiguous by definition.
        TypeCode("PURCHASE", Direction.OUT, "Card purchase"),
        TypeCode("INTEREST PAID", Direction.IN, "Interest credited"),
        TypeCode("ATM WITHDRAWAL", Direction.OUT, "ATM withdrawal"),
        TypeCode("WITHDRAWAL", Direction.OUT, "Withdrawal"),
        TypeCode("DEPOSIT", Direction.IN, "Deposit"),
        TypeCode("CHECK", Direction.OUT, "Cheque paid"),
        TypeCode("SERVICE CHARGE", Direction.OUT, "Fee"),
        TypeCode("MONTHLY MAINTENANCE FEE", Direction.OUT, "Fee"),
        TypeCode("REFUND", Direction.IN, "Refund"),
        # Can post either way; balance validation decides.
        TypeCode("TRANSFER", Direction.AMBIGUOUS, "Transfer"),
        TypeCode("ONLINE TRANSFER", Direction.AMBIGUOUS, "Online transfer"),
        TypeCode("WIRE", Direction.AMBIGUOUS, "Wire"),
        TypeCode("ACH", Direction.AMBIGUOUS, "ACH"),
        TypeCode("ADJUSTMENT", Direction.AMBIGUOUS, "Adjustment"),
        TypeCode("REVERSAL", Direction.AMBIGUOUS, "Reversal"),
    ),
    balance_marker="sigil",
    description_max_col=40,
    # Measured: balance ends col 140 / withdrawals 119 / deposits 97 on page 1,
    # and 118 / 97 / 75 on later pages — a constant 43-character band either way.
    amount_band_width=50,
    paid_in_side="left",  # DEPOSITS column sits left of WITHDRAWALS
    default_in_out_split=100,
    balance_min_col=120,
    checkpoint_patterns=[
        re.compile(r"\bOPENING BALANCE\b", re.I),
        re.compile(r"\bENDING BALANCE\b", re.I),
        re.compile(r"\bBALANCE (BROUGHT|CARRIED) FORWARD\b", re.I),
    ],
    noise_patterns=[
        re.compile(r"CONTINUED (ON NEXT|FROM PREVIOUS) PAGE", re.I),
        re.compile(r"^\s*Page \d+ of \d+\s*$", re.I),
        re.compile(r"^\s*DEPOSITS\s+WITHDRAWALS\s*$", re.I),
        re.compile(r"^\s*DATE\s+& OTHER\s+& OTHER\s*$", re.I),
    ],
)
