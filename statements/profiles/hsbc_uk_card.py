"""HSBC UK — Premier World Elite credit card, sterling.

Derived from and validated against a real statement. This is a liability
account and its layout differs from every deposit-account profile here:

* **Two dates per line** — "Received By Us" (posting) and "Transaction Date".
  The second is the one that belongs in `txn_date`; the first is kept in
  `posting_date`.
* **No type-code column and no running balance.** A leading date pair is what
  opens a transaction, and only the statement-level check can validate.
* **One amount column, pre-signed.** A `CR` suffix marks the entries that go
  the other way — a refund or a payment to the card.
* **Money out increases the balance**, because the balance is what is owed.
* **Interest is a transaction.** The statement's Debits total includes the
  interest charged, so the `TOTAL INTEREST CHARGED` line has to be picked up
  or the statement is short by exactly that amount. Its itemised breakdown
  above it, and the estimate for next month below it, must not be — either
  would double-count.

HSBC's PDF kerning splits words unpredictably ("STATEM ENT", "M inim um
paym ent", "Credit Lim it"), so patterns here avoid the affected words rather
than trying to match through them.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .base import Direction, Profile, TypeCode


def parse_card_date(text: str) -> date:
    """'16 Mar 24' or '16 April 2024' -> date. Day-first throughout."""
    cleaned = " ".join(text.split())
    for fmt in ("%d %b %y", "%d %B %Y", "%d %b %Y", "%d %B %y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised card date: {text!r}")


HSBC_UK_CARD = Profile(
    name="hsbc-uk-card",
    bank="HSBC UK",
    description="HSBC UK Premier World Elite credit card (GBP)",
    currency="GBP",
    table_start=[
        re.compile(r"^\s*Received\s+By\s+Us\s+Transaction\s+Date", re.I),
        # Continuation sheets repeat only the card number, not the column header.
        re.compile(r"^\s*Statement Date\s+.*Sheet number", re.I),
    ],
    continues_by_default=True,
    table_stop=[
        re.compile(r"We now provide", re.I),
        re.compile(r"^\s*Summary Box\b", re.I),
        re.compile(r"DETACH HERE", re.I),
        re.compile(r"https?://", re.I),
    ],
    summary_patterns={
        "opening_balance": re.compile(r"Previous Balance\s+([\d,]+\.\d{2})", re.I),
        "closing_balance": re.compile(r"New Balance\s+([\d,]+\.\d{2})", re.I),
        "printed_paid_out": re.compile(r"^\s*Debits\s+([\d,]+\.\d{2})", re.I | re.M),
        "printed_paid_in": re.compile(r"^\s*Credits\s+([\d,]+\.\d{2})", re.I | re.M),
    },
    # Only the statement date is printed; the period start is not, and is left
    # blank rather than inferred from the first transaction.
    period_pattern=re.compile(r"Statement Date\s+(\d{1,2}\s+\w{3,9}\s+\d{4})", re.I),
    account_pattern=re.compile(r"\b\d{4}\s+\d{4}\s+\d{4}\s+(\d{4})\b"),
    # "Sheet number 1 of 4" numbers pages within one statement, not sheets
    # across statements, so it must not drive the continuity check.
    sheet_pattern=None,
    # The primary cardholder, from the address block on page 1.
    owner_pattern=re.compile(
        r"^\s*((?:Professor|Mr|Mrs|Ms|Dr|Miss)\s+[A-Z][\w'\u2019-]*(?:\s+[A-Z][\w'\u2019-]*)*)\s*$",
        re.M,
    ),
    # A statement can carry several cardholders in sequence: each section names
    # its holder beside that card's number, and everything after belongs to them.
    owner_section_pattern=re.compile(
        r"^\s*(?P<owner>[A-Z][^\d]{3,40}?)\s{2,}(?P<account>\d{4}\s+\d{4}\s+\d{4}\s+\d{4})\s*$",
        re.M,
    ),
    page_pattern=re.compile(r"Sheet number\s+(\d+)\s+of\s+(\d+)", re.I),
    date_pattern=re.compile(
        r"^\s*(?P<posting>\d{1,2}\s+\w{3}\s+\d{2})\s+(?P<txn>\d{1,2}\s+\w{3}\s+\d{2})\s"
    ),
    parse_date=parse_card_date,
    date_starts_transaction=True,
    code_source="description_prefix",
    codes=(
        TypeCode(")))", Direction.OUT, "Contactless"),
        TypeCode("NON-STERLING TRANSACTION FEE", Direction.OUT, "FX fee"),
        TypeCode("DIRECT DEBIT PAYMENT", Direction.IN, "Payment to card"),
        TypeCode("TOTAL INTEREST CHARGED", Direction.OUT, "Interest"),
        TypeCode("CASH ADVANCE", Direction.OUT, "Cash advance"),
        TypeCode("BALANCE TRANSFER", Direction.AMBIGUOUS, "Balance transfer"),
    ),
    default_code="PUR",
    default_direction=Direction.OUT,
    balance_marker="none",
    amount_sign_mode="suffix",
    balance_sign="liability",
    # The exchange-rate detail lines ("55.50 EUR@1.1681") sit far left of the
    # amount column, which itself moves from column 94 to 121 across sheets.
    description_max_col=60,
    amount_band_width=45,
    default_in_out_split=0,
    balance_min_col=999,  # no balance column exists
    checkpoint_patterns=[],
    noise_patterns=[
        re.compile(r"MasterCard Exchange Rate", re.I),
        re.compile(r"^\s*Summary Of Interest", re.I),
        re.compile(r"^\s*Estimated interest", re.I),
        # The per-rate breakdown that TOTAL INTEREST CHARGED already sums.
        re.compile(r"^\s*Interest on .* per month", re.I),
        re.compile(r"Your Transaction Details", re.I),
        re.compile(r"^\s*Received\s+By\s+Us\s+Transaction\s+Date", re.I),
        re.compile(r"NO TRANSACTIONS FOR THIS ACCOUNT", re.I),
        re.compile(r"NO INTEREST CHARGED", re.I),
        re.compile(r"^\s*Card number\s*$", re.I),
        # The second line of a cardholder name wrapped beside the card number.
        re.compile(r"^\s*[A-Z][a-z]+\s*$"),
        re.compile(r"^\s*Statement Date\b", re.I),
        re.compile(r"^\s*Your HSBC", re.I),
        re.compile(r"^\s*\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s*$"),
    ],
)
