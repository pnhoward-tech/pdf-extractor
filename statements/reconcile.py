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


def _delta(transactions: list[Transaction]) -> int:
    """Net effect on the balance: money in minus money out."""
    return sum(-t.signed for t in transactions)


def _apply(transactions: list[Transaction], flipped: tuple[int, ...]) -> None:
    for index in flipped:
        txn = transactions[index]
        txn.direction = Direction.IN if txn.direction is Direction.OUT else Direction.OUT


def resolve_segment(
    transactions: list[Transaction], opening: int, closing: int
) -> tuple[bool, str]:
    """Make one stretch of transactions add up to the change in balance.

    Returns (resolved, note). Only transactions whose direction the type code
    left ambiguous are candidates for flipping — a direct debit is never a
    credit, however inconvenient that is for the arithmetic.
    """
    target = closing - opening
    if _delta(transactions) == target:
        return True, ""

    candidates = [i for i, t in enumerate(transactions) if not t.direction_certain]
    if not candidates:
        return False, (
            f"UNRESOLVED - manual review: balance moves by {format_money(target)} but "
            f"transactions total {format_money(_delta(transactions))}, and no "
            f"ambiguous-direction transaction is available to flip"
        )

    # One wrong transaction is the common case; flipping it changes the total
    # by twice its amount.
    for index in candidates:
        _apply(transactions, (index,))
        if _delta(transactions) == target:
            return True, f"flipped: single transaction ({transactions[index].type_code})"
        _apply(transactions, (index,))

    # A whole page whose columns were read one band across shows up as every
    # ambiguous transaction in the stretch being wrong the same way.
    if len(candidates) > 1:
        _apply(transactions, tuple(candidates))
        if _delta(transactions) == target:
            return True, "flipped: page-wide column recalibration"
        _apply(transactions, tuple(candidates))

    if len(candidates) <= MAX_BRUTE_FORCE:
        for size in range(2, len(candidates)):
            for subset in combinations(candidates, size):
                _apply(transactions, subset)
                if _delta(transactions) == target:
                    return True, f"flipped: {size} transactions resolved by balance search"
                _apply(transactions, subset)

    return False, (
        f"UNRESOLVED - manual review: balance moves by {format_money(target)} but "
        f"transactions total {format_money(_delta(transactions))}"
    )


def reconcile(doc: StatementDoc) -> StatementCheck:
    """Validate a parsed statement, correcting what the balances can settle."""
    notes: list[str] = []
    anchor = doc.opening_balance
    if anchor is None and doc.checkpoints:
        anchor = doc.checkpoints[0].balance

    segment: list[Transaction] = []
    for txn in doc.transactions:
        segment.append(txn)
        if txn.printed_balance is None or anchor is None:
            continue
        resolved, note = resolve_segment(segment, anchor, txn.printed_balance)
        _record(segment, resolved, note, notes)
        anchor = txn.printed_balance
        segment = []

    if segment and anchor is not None and doc.closing_balance is not None:
        resolved, note = resolve_segment(segment, anchor, doc.closing_balance)
        _record(segment, resolved, note, notes)

    paid_in = sum(t.amount for t in doc.transactions if t.direction is Direction.IN)
    paid_out = sum(t.amount for t in doc.transactions if t.direction is Direction.OUT)

    ok = True
    if doc.opening_balance is None or doc.closing_balance is None:
        ok = False
        notes.append("Opening or closing balance missing from the summary box.")
    elif doc.opening_balance + paid_in - paid_out != doc.closing_balance:
        ok = False
        gap = doc.closing_balance - (doc.opening_balance + paid_in - paid_out)
        notes.append(
            f"Statement does not reconcile: opening {format_money(doc.opening_balance)} "
            f"+ in {format_money(paid_in)} - out {format_money(paid_out)} != closing "
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
    """Flag gaps in the bank's own sheet numbering — a sign of a partial download."""
    numbered = [d for d in docs if d.sheet_number.isdigit()]
    if len(numbered) < 2:
        return []
    numbered.sort(key=lambda d: (d.period_start or d.source_file, int(d.sheet_number)))
    warnings = []
    for previous, current in zip(numbered, numbered[1:]):
        expected = int(previous.sheet_number) + 1
        actual = int(current.sheet_number)
        if actual != expected:
            warnings.append(
                f"Sheet numbers jump from {previous.sheet_number} ({previous.source_file}) "
                f"to {current.sheet_number} ({current.source_file}) — expected {expected}. "
                "A statement may be missing from the folder."
            )
    return warnings
