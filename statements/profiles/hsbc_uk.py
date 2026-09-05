"""HSBC UK — Premier / current account, sterling.

Validated against a real statement. Its shape in practice:

* Nearly every transaction spans two or more lines. The code and payee sit on
  the first, the location or reference and the amount on the next — so the
  amount is normally *not* on the line that opens the transaction.
* The running balance is printed once per day group, against that day's last
  transaction. Segments between checkpoints therefore hold several
  transactions, which is what the flip-resolution search is for.
* Sheet numbers run continuously across statements (858, 859, 860 ...), so a
  gap between consecutive statements means a missing document.
* PDF kerning splits words and numbers unpredictably — "Ope ning Balance",
  "Paym e nts In", "£35,349 .65" — so every label pattern here is built with
  `loose()`, which tolerates spaces anywhere inside a word.

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

from ..text import loose, loose_pattern
from .base import Direction, Profile, TypeCode


def parse_uk_date(text: str) -> date:
    """'05 Jan 25' -> date. Day-first, never month-first."""
    cleaned = " ".join(text.split())
    # Transaction lines abbreviate the month ("30 Jun 26"); the period line
    # spells it out ("30 June to 29 July 2026").
    for fmt in ("%d %b %y", "%d %b %Y", "%d %B %Y", "%d %B %y", "%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised UK date: {text!r}")


HSBC_UK_PREMIER = Profile(
    name="hsbc-uk",
    bank="HSBC UK",
    description="HSBC UK Premier / current account (GBP)",
    currency="GBP",
    # Anchored on the two words either side of the first column gap; the rest
    # of the header ("Pay m e nt t y p e and de t ails") is unreliable.
    table_start=[re.compile(r"^\s*" + loose("Date") + r"\s+" + loose("Payment"), re.I)],
    table_continues=[loose_pattern("BALANCE BROUGHT FORWARD")],
    table_stop=[
        loose_pattern("Information about the Financial Services Compensation Scheme"),
        loose_pattern("Your Premier Bank Account details in detail"),
        re.compile(r"^\s*" + loose("Interest rate"), re.I),
        re.compile(loose("AER") + r"\b.*\b" + loose("Gross"), re.I),
    ],
    summary_patterns={
        "opening_balance": re.compile(
            loose("Opening Balance") + r"\s+£?\s*([\d, ]+\.\s?\d{2})", re.I
        ),
        "closing_balance": re.compile(
            loose("Closing Balance") + r"\s+£?\s*([\d, ]+\.\s?\d{2})", re.I
        ),
        "printed_paid_in": re.compile(
            "(?:" + loose("Payments In") + "|" + loose("Total Paid In") + r")\s+£?\s*([\d, ]+\.\s?\d{2})",
            re.I,
        ),
        "printed_paid_out": re.compile(
            "(?:" + loose("Payments Out") + "|" + loose("Total Paid Out") + r")\s+£?\s*([\d, ]+\.\s?\d{2})",
            re.I,
        ),
    },
    # "30 June to 29 July 2026" — the year appears only once, at the end.
    period_pattern=re.compile(
        r"(\d{1,2}\s+\w{3,9}(?:\s+\d{4})?)\s+to\s+(\d{1,2}\s+\w{3,9}\s+\d{4})", re.I
    ),
    # Sortcode, account number and sheet number sit together on one line under
    # the account name. Anchoring on the triple avoids matching a phone number.
    account_pattern=re.compile(r"\b\d{2}-\d{2}-\d{2}\s+(\d{8})\s+\d+\s*$", re.M),
    # Runs continuously across statements, so gaps mean a missing document.
    sheet_pattern=re.compile(r"\b\d{2}-\d{2}-\d{2}\s+\d{8}\s+(\d+)\s*$", re.M),
    page_pattern=re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I),
    # The account name sits directly above the sortcode/account/sheet triple.
    owner_pattern=re.compile(r"^\s*(\S.*?)\s{2,}\d{2}-\d{2}-\d{2}\s+\d{8}\s+\d+\s*$", re.M),
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
        re.compile(r"^\s*" + loose("Date") + r"\s+" + loose("Payment"), re.I),
        re.compile(r"^\s*" + loose("Account Name"), re.I),
        re.compile(r"^\s*" + loose("Your Premier Bank Account details") + r"\s*$", re.I),
        re.compile(r"^\s*" + loose("Your HSBC"), re.I),
        re.compile(r"Contact tel|Text phone|www\.hsbc|see reverse", re.I),
        re.compile(r"^\s*\w?\s*$"),  # stray single characters
        re.compile(r"^\s*\d{1,2}\s+\w{3,9}\s+to\s+", re.I),
        re.compile(r"^\s*\d{2}-\d{2}-\d{2}\s+\d{8}\s+\d+\s*$"),
        # HSBC's registered-office footer, printed below the table on each page.
        re.compile(r"Cornmarket Street Oxford", re.I),
        re.compile(r"^\s*Registered (in England|Office)", re.I),
    ],
)
