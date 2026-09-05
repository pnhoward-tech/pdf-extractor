"""Balance validation: the step that decides whether anything ships."""

from datetime import date

import pytest

from statements.parse import StatementDoc, Transaction
from statements.profiles import Direction
from statements.reconcile import check_sheet_continuity, reconcile, resolve_segment


def txn(amount: int, direction: Direction, *, certain: bool = True, balance: int | None = None,
        code: str = "VIS") -> Transaction:
    return Transaction(
        source_file="s.pdf", page_number=1, line_number=1, txn_date=date(2025, 1, 1),
        posting_date=None,
        type_code=code, description="d", amount=amount, direction=direction,
        direction_certain=certain, printed_balance=balance,
    )


def test_segment_that_already_adds_up_is_left_alone():
    txns = [txn(10000, Direction.OUT), txn(5000, Direction.IN)]
    resolved, note = resolve_segment(txns, 100000, 95000)
    assert resolved and note == ""
    assert [t.direction for t in txns] == [Direction.OUT, Direction.IN]


def test_single_wrong_transaction_is_flipped():
    """A refund read as a purchase: flipping it moves the total by twice its amount."""
    txns = [txn(20000, Direction.OUT, certain=True, code="DD"),
            txn(10000, Direction.OUT, certain=False)]
    resolved, note = resolve_segment(txns, 100000, 90000)
    assert resolved
    assert "single transaction" in note
    assert txns[1].direction is Direction.IN
    assert txns[0].direction is Direction.OUT  # the direct debit is untouched


def test_whole_page_read_one_column_across_is_flipped_together():
    txns = [txn(1000, Direction.OUT, certain=False) for _ in range(4)]
    resolved, note = resolve_segment(txns, 100000, 104000)
    assert resolved
    assert note == "flipped: page-wide column recalibration"
    assert all(t.direction is Direction.IN for t in txns)


def test_subset_search_resolves_a_mixed_segment():
    txns = [txn(1000, Direction.OUT, certain=False), txn(2000, Direction.OUT, certain=False),
            txn(3000, Direction.OUT, certain=False), txn(4000, Direction.OUT, certain=False)]
    # Flipping the 2000 and 4000 gives -1000 - 3000 + 2000 + 4000 = +2000.
    resolved, note = resolve_segment(txns, 100000, 102000)
    assert resolved
    assert "resolved by balance search" in note
    assert [t.direction for t in txns] == [
        Direction.OUT, Direction.IN, Direction.OUT, Direction.IN
    ]


def test_certain_transactions_are_never_flipped_to_force_a_fit():
    """A direct debit cannot be a credit, however convenient for the arithmetic."""
    txns = [txn(10000, Direction.OUT, certain=True, code="DD")]
    resolved, note = resolve_segment(txns, 100000, 110000)
    assert not resolved
    assert "UNRESOLVED" in note
    assert txns[0].direction is Direction.OUT


def test_unresolvable_segment_is_flagged_not_guessed():
    txns = [txn(10000, Direction.OUT, certain=False), txn(3333, Direction.OUT, certain=False)]
    resolved, note = resolve_segment(txns, 100000, 100001)
    assert not resolved
    assert "UNRESOLVED - manual review" in note


def _doc(transactions, opening=100000, closing=None, printed_in=None, printed_out=None):
    paid_in = sum(t.amount for t in transactions if t.direction is Direction.IN)
    paid_out = sum(t.amount for t in transactions if t.direction is Direction.OUT)
    return StatementDoc(
        source_file="s.pdf", profile="test", currency="GBP",
        opening_balance=opening,
        closing_balance=opening + paid_in - paid_out if closing is None else closing,
        printed_paid_in=printed_in, printed_paid_out=printed_out,
        transactions=transactions,
    )


def test_statement_passes_when_everything_agrees():
    check = reconcile(_doc([txn(10000, Direction.OUT, balance=90000)],
                           printed_in=0, printed_out=10000))
    assert check.ok and check.status == "OK"
    assert check.computed_paid_out == 10000


def test_statement_fails_when_totals_disagree_with_the_printed_box():
    check = reconcile(_doc([txn(10000, Direction.OUT, balance=90000)],
                           printed_in=0, printed_out=12000))
    assert not check.ok
    assert any("does not match the printed total" in n for n in check.notes)


def test_failing_statement_suggests_the_half_the_gap_search():
    """Flipping one transaction moves the total by twice its amount, so the
    suspect is the one worth exactly half the discrepancy."""
    doc = _doc([txn(10000, Direction.OUT, certain=True, code="DD")], opening=100000, closing=100000)
    check = reconcile(doc)
    assert not check.ok
    assert any("exactly 50.00" in n for n in check.notes)


def test_missing_summary_balances_fail_the_check():
    doc = _doc([txn(10000, Direction.OUT)])
    doc.opening_balance = None
    check = reconcile(doc)
    assert not check.ok
    assert any("missing from the summary box" in n for n in check.notes)


def test_sheet_continuity_flags_a_gap():
    docs = [
        StatementDoc(source_file="a.pdf", profile="p", currency="GBP",
                     sheet_numbers=["40", "41"], period_start=date(2025, 1, 1)),
        StatementDoc(source_file="b.pdf", profile="p", currency="GBP",
                     sheet_numbers=["44"], period_start=date(2025, 2, 1)),
    ]
    warnings = check_sheet_continuity(docs)
    assert len(warnings) == 1
    assert "expected 42" in warnings[0]


def test_sheet_continuity_quiet_when_contiguous():
    docs = [
        StatementDoc(source_file="a.pdf", profile="p", currency="GBP",
                     sheet_numbers=["40", "41"], period_start=date(2025, 1, 1)),
        StatementDoc(source_file="b.pdf", profile="p", currency="GBP",
                     sheet_numbers=["42", "43"], period_start=date(2025, 2, 1)),
    ]
    assert check_sheet_continuity(docs) == []


# --------------------------------------------------------------------------- #
# Liability accounts and date sanity
# --------------------------------------------------------------------------- #

def test_card_balance_rises_with_spending():
    """On a card, money out increases what is owed."""
    doc = StatementDoc(
        source_file="c.pdf", profile="card", currency="GBP",
        opening_balance=100000, closing_balance=125000,
        transactions=[txn(30000, Direction.OUT), txn(5000, Direction.IN)],
    )
    assert reconcile(doc, liability=True).ok


def test_deposit_convention_applied_to_a_card_fails():
    doc = StatementDoc(
        source_file="c.pdf", profile="card", currency="GBP",
        opening_balance=100000, closing_balance=125000,
        transactions=[txn(30000, Direction.OUT), txn(5000, Direction.IN)],
    )
    assert not reconcile(doc, liability=False).ok


def test_backwards_period_is_flagged():
    """The signature of a misread year — the OCR failure the balance check
    cannot see, because the amounts still add up."""
    doc = StatementDoc(
        source_file="s.pdf", profile="p", currency="USD",
        opening_balance=100000, closing_balance=100000,
        period_start=date(2025, 12, 14), period_end=date(2024, 1, 11),
    )
    doc.ocr = True
    check = reconcile(doc)
    assert not check.ok
    assert any("runs backwards" in n and "OCR" in n for n in check.notes)


def test_backwards_period_without_ocr_blames_the_profile():
    doc = StatementDoc(
        source_file="s.pdf", profile="p", currency="USD",
        opening_balance=100000, closing_balance=100000,
        period_start=date(2025, 1, 1), period_end=date(2024, 1, 1),
    )
    check = reconcile(doc)
    assert any("period pattern" in n for n in check.notes)


def test_transaction_dated_outside_the_period_is_flagged():
    stray = txn(10000, Direction.OUT, balance=90000)
    stray.txn_date = date(2023, 5, 1)
    doc = StatementDoc(
        source_file="s.pdf", profile="p", currency="USD",
        opening_balance=100000, closing_balance=90000,
        period_start=date(2025, 1, 1), period_end=date(2025, 1, 31),
        transactions=[stray],
    )
    check = reconcile(doc)
    assert not check.ok
    assert any("outside the statement period" in n for n in check.notes)


def test_dates_inside_the_period_pass():
    inside = txn(10000, Direction.OUT, balance=90000)
    inside.txn_date = date(2025, 1, 15)
    doc = StatementDoc(
        source_file="s.pdf", profile="p", currency="USD",
        opening_balance=100000, closing_balance=90000,
        period_start=date(2025, 1, 1), period_end=date(2025, 1, 31),
        transactions=[inside],
    )
    assert reconcile(doc).ok
