"""Checking that the dates came out right.

Date fields vary more than anything else between banks: month-first and
day-first look identical on the twelfth of a month, two-digit years are
ambiguous about the century, and a scan can turn one digit into another. Every
date is therefore checked against things the statement already tells us — its
period, and the order its transactions are printed in — rather than trusted
because it parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .parse import StatementDoc, Transaction

# A statement lists transactions in order. A few out-of-order rows are normal
# (a posting date differing from a transaction date); many are not.
DISORDER_TOLERANCE = 0.15
# Below this many transactions, one row out of order says nothing.
MIN_FOR_ORDER_CHECK = 8
# The longest a statement's transactions can plausibly predate its end date,
# used where only the statement date is printed.
MAX_BILLING_DAYS = 70


@dataclass
class DateReport:
    checked: int
    outside_period: list[Transaction]
    out_of_order: int
    ambiguous: list[Transaction]
    notes: list[str]

    @property
    def ok(self) -> bool:
        return not self.outside_period and not self.notes


def is_ambiguous(value: date) -> bool:
    """True where swapping day and month would also be a valid date.

    03/04 could be 3 April or 4 March; 25/12 could only ever be 25 December.
    Rows that are ambiguous in isolation are the ones worth marking, so a
    misread of the whole column can be spotted from the output.
    """
    return value.day <= 12 and value.month <= 12 and value.day != value.month


def check_dates(doc: StatementDoc, chronological: bool = True) -> DateReport:
    """Validate a statement's dates and stamp each transaction's confidence.

    `chronological` says whether this layout lists transactions in date order.
    Section-organised statements do not, so their ordering proves nothing.

    The day/month reading is judged for the column as a whole, not row by row.
    Roughly 40% of dates are individually ambiguous — any day of 12 or less —
    so flagging each one would bury the cases that matter. What settles it is
    whether the column runs in order and sits inside the printed period; when
    both hold, the format is confirmed and every row is `certain`.
    """
    dated = [t for t in doc.transactions if t.txn_date]
    notes: list[str] = []

    # Posting can lag a day or two either side of the printed period.
    low = high = None
    if doc.period_end:
        high = doc.period_end + timedelta(days=3)
        # A card prints only its statement date. Its transactions still have to
        # fall in the billing period before it, which is corroboration enough
        # to settle the day/month reading.
        low = (doc.period_start - timedelta(days=3)) if doc.period_start else (
            doc.period_end - timedelta(days=MAX_BILLING_DAYS)
        )
    outside = [t for t in dated if low and not (low <= t.txn_date <= high)]

    # Order is judged on whichever date the statement is sorted by. Where both
    # are printed that is the posting date: a card lists by when the bank
    # received it, so its transaction dates legitimately jump around.
    sort_dates = [t.posting_date or t.txn_date for t in dated]
    disorder = sum(1 for a, b in zip(sort_dates, sort_dates[1:]) if a > b)
    # Statements that group transactions under "credits" then "debits" headings
    # are ordered by kind, not by date, so the check does not apply to them.
    disordered = (
        chronological
        and len(dated) >= MIN_FOR_ORDER_CHECK
        and disorder > len(dated) * DISORDER_TOLERANCE
    )
    if disordered:
        notes.append(
            f"{disorder} of {len(dated)} transactions are out of date order. "
            "The day and month may have been read the wrong way round."
        )

    ambiguous = [t for t in dated if is_ambiguous(t.txn_date)]
    verified = not outside and not disordered and low is not None

    for txn in doc.transactions:
        if not txn.txn_date:
            txn.date_confidence = "missing"
        elif txn in outside:
            txn.date_confidence = "outside_period"
        elif disordered:
            txn.date_confidence = "order_suspect"
        elif verified:
            # The column as a whole is corroborated by the period and the order.
            txn.date_confidence = "certain"
        elif is_ambiguous(txn.txn_date):
            txn.date_confidence = "day_month_unverified"
        else:
            txn.date_confidence = "certain"

    if outside:
        shown = ", ".join(sorted({str(t.txn_date) for t in outside})[:4])
        notes.append(
            f"{len(outside)} transaction(s) dated outside the statement period "
            f"({doc.period_start or low} to {doc.period_end}): {shown}."
        )
    if doc.period_start and doc.period_end and doc.period_start > doc.period_end:
        notes.append(f"Statement period runs backwards: {doc.period_start} to {doc.period_end}.")
    if not verified and not notes and dated:
        notes.append(
            "Dates could not be corroborated against a statement period; "
            f"{len(ambiguous)} of {len(dated)} would also parse the other way round."
        )

    return DateReport(
        checked=len(dated),
        outside_period=outside,
        out_of_order=disorder,
        ambiguous=ambiguous,
        notes=notes,
    )
