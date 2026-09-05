"""Balance validation. Nothing ships unless it reconciles to the penny.

Two levels:

* Segment level — between each pair of printed balances, money in minus money
  out must equal the change in balance. Where it doesn't, and the culprits are
  transactions whose type code can't settle direction on its own, flipping the
  right subset is what fixes it.
* Statement level — opening + total in - total out must equal closing, exactly.
  A statement that fails this is flagged, not shipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations

from .money import format_money
from .parse import StatementDoc, Transaction
from .profiles import Direction

# Above this many ambiguous transactions in one segment, the subset search is
# skipped — an unresolved flag beats an arbitrary combination that happens to add up.
MAX_BRUTE_FORCE = 12


@dataclass
class StatementCheck:
    source_file: str
    opening_balance: int | None
    closing_balance: int | None
    computed_paid_in: int
    computed_paid_out: int
    printed_paid_in: int | None
    printed_paid_out: int | None
    ok: bool
    notes: list[str]

    @property
    def status(self) -> str:
        return "OK" if self.ok else "CHECK"


def _delta(transactions: list[Transaction], liability: bool = False) -> int:
    """Net effect on the balance.

    On a deposit account money in raises the balance. On a card the balance is
    what you owe, so it is money *out* that raises it.
    """
    net = sum(-t.signed for t in transactions)
    return -net if liability else net


def _apply(transactions: list[Transaction], flipped: tuple[int, ...]) -> None:
    for index in flipped:
        txn = transactions[index]
        txn.direction = Direction.IN if txn.direction is Direction.OUT else Direction.OUT


def resolve_segment(
    transactions: list[Transaction], opening: int, closing: int, liability: bool = False
) -> tuple[bool, str]:
    """Make one stretch of transactions add up to the change in balance.

    Returns (resolved, note). Only transactions whose direction the type code
    left ambiguous are candidates for flipping — a direct debit is never a
    credit, however inconvenient that is for the arithmetic.
    """
    target = closing - opening
    if _delta(transactions, liability) == target:
        return True, ""

    candidates = [i for i, t in enumerate(transactions) if not t.direction_certain]
    if not candidates:
        return False, (
            f"UNRESOLVED - manual review: balance moves by {format_money(target)} but "
            f"transactions total {format_money(_delta(transactions, liability))}, and no "
            f"ambiguous-direction transaction is available to flip"
        )

    # One wrong transaction is the common case; flipping it changes the total
    # by twice its amount.
    for index in candidates:
        _apply(transactions, (index,))
        if _delta(transactions, liability) == target:
            return True, f"flipped: single transaction ({transactions[index].type_code})"
        _apply(transactions, (index,))

    # A whole page whose columns were read one band across shows up as every
    # ambiguous transaction in the stretch being wrong the same way.
    if len(candidates) > 1:
        _apply(transactions, tuple(candidates))
        if _delta(transactions, liability) == target:
            return True, "flipped: page-wide column recalibration"
        _apply(transactions, tuple(candidates))

    if len(candidates) <= MAX_BRUTE_FORCE:
        for size in range(2, len(candidates)):
            for subset in combinations(candidates, size):
                _apply(transactions, subset)
                if _delta(transactions, liability) == target:
                    return True, f"flipped: {size} transactions resolved by balance search"
                _apply(transactions, subset)

    return False, (
        f"UNRESOLVED - manual review: balance moves by {format_money(target)} but "
        f"transactions total {format_money(_delta(transactions, liability))}"
    )


def reconcile(doc: StatementDoc, liability: bool = False) -> StatementCheck:
    """Validate a parsed statement, correcting what the balances can settle.

    `liability` marks a card account, where money out increases the balance.

    Dates are not checked here — `dates.check_dates` owns that, and
    `batch.run` folds its findings in, so the two cannot report the same
    problem in two different wordings.
    """
    notes: list[str] = []
    anchor = doc.opening_balance
    if anchor is None and doc.checkpoints:
        anchor = doc.checkpoints[0].balance

    # Transactions and standalone balance lines interleave, and both anchor a
    # segment. Walking them in document order is what keeps a
    # "BALANCE CARRIED FORWARD" at the foot of a page from being skipped.
    events: list[tuple[int, int, str, object]] = [
        (t.page_number, t.line_number, "txn", t) for t in doc.transactions
    ]
    events += [
        (c.page_number, c.line_number, "checkpoint", c) for c in doc.checkpoints
    ]
    events.sort(key=lambda e: (e[0], e[1]))

    segment: list[Transaction] = []
    for _, _, kind, item in events:
        if kind == "txn":
            segment.append(item)
            balance = item.printed_balance
        else:
            balance = item.balance
        if balance is None or anchor is None:
            if anchor is None and balance is not None:
                anchor = balance
            continue
        if not segment:
            # Consecutive checkpoints with nothing between them: the balance
            # must simply not have moved.
            if balance != anchor:
                notes.append(
                    f"p.{item.page_number}: balance jumps from "
                    f"{format_money(anchor)} to {format_money(balance)} with no "
                    "transactions in between — a line was probably not parsed."
                )
                ok_gap = False  # noqa: F841 - recorded via notes below
            anchor = balance
            continue
        resolved, note = resolve_segment(segment, anchor, balance, liability)
        _record(segment, resolved, note, notes)
        anchor = balance
        segment = []

    if segment and anchor is not None and doc.closing_balance is not None:
        resolved, note = resolve_segment(segment, anchor, doc.closing_balance, liability)
        _record(segment, resolved, note, notes)

    paid_in = sum(t.amount for t in doc.transactions if t.direction is Direction.IN)
    paid_out = sum(t.amount for t in doc.transactions if t.direction is Direction.OUT)

    ok = True
    if doc.opening_balance is None or doc.closing_balance is None:
        ok = False
        notes.append("Opening or closing balance missing from the summary box.")
    else:
        # On a card the balance is what is owed, so spending raises it.
        movement = paid_out - paid_in if liability else paid_in - paid_out
        gap = doc.closing_balance - (doc.opening_balance + movement)
        if gap:
            ok = False
            added, removed = ("out", "in") if liability else ("in", "out")
            added_total = format_money(paid_out if liability else paid_in)
            removed_total = format_money(paid_in if liability else paid_out)
            notes.append(
                f"Statement does not reconcile: opening "
                f"{format_money(doc.opening_balance)} + {added} {added_total} - "
                f"{removed} {removed_total} != closing "
                f"{format_money(doc.closing_balance)} (off by {format_money(gap)}). "
                f"Look for a transaction of exactly {format_money(abs(gap) // 2)} "
                "on the wrong side, or a multi-line transaction parsed short."
            )

    for label, computed, printed in (
        ("paid in", paid_in, doc.printed_paid_in),
        ("paid out", paid_out, doc.printed_paid_out),
    ):
        if printed is not None and computed != printed:
            ok = False
            notes.append(
                f"Computed {label} {format_money(computed)} does not match the "
                f"printed total {format_money(printed)}."
            )

    if any("UNRESOLVED" in t.reconciliation_note for t in doc.transactions):
        ok = False

    return StatementCheck(
        source_file=doc.source_file,
        opening_balance=doc.opening_balance,
        closing_balance=doc.closing_balance,
        computed_paid_in=paid_in,
        computed_paid_out=paid_out,
        printed_paid_in=doc.printed_paid_in,
        printed_paid_out=doc.printed_paid_out,
        ok=ok,
        notes=notes,
    )


def _record(segment: list[Transaction], resolved: bool, note: str, notes: list[str]) -> None:
    for txn in segment:
        if not txn.direction_certain:
            txn.direction_confidence = "resolved_by_balance" if resolved else "unresolved"
        if note:
            txn.reconciliation_note = note
    if note and not resolved:
        first, last = segment[0], segment[-1]
        notes.append(f"p.{first.page_number} lines {first.line_number}-{last.line_number}: {note}")


def check_sheet_continuity(docs: list[StatementDoc]) -> list[str]:
    """Flag gaps in the bank's own sheet numbering — a sign of a missing
    statement. A statement spans a run of sheets (858, 859, 860 ...), so the
    comparison is its last sheet against the next statement's first."""
    numbered = [d for d in docs if d.sheet_numbers and all(s.isdigit() for s in d.sheet_numbers)]
    if len(numbered) < 2:
        return []
    numbered.sort(key=lambda d: (d.period_start or date.min, int(d.sheet_numbers[0])))
    warnings = []
    for previous, current in zip(numbered, numbered[1:]):
        expected = int(previous.sheet_numbers[-1]) + 1
        actual = int(current.sheet_numbers[0])
        if actual != expected:
            warnings.append(
                f"Sheet numbers jump from {previous.sheet_numbers[-1]} "
                f"({previous.source_file}) to {actual} ({current.source_file}) — "
                f"expected {expected}. A statement may be missing from the folder."
            )
    return warnings
