"""HSBC UK parsing.

The profile itself is derived from a written spec rather than from statements
in hand, so these tests pin its behaviour against layout text built to that
spec. Treat a real UK batch as unproven until its reconciliation report is
clean — that report is what would catch a wrong column number here.
"""

from datetime import date

import pytest

from statements.parse import parse_statement
from statements.profiles import Direction, get_profile
from statements.profiles.hsbc_uk import parse_uk_date
from statements.reconcile import reconcile
from tests.bank.fixtures import uk_statement


@pytest.fixture
def profile():
    return get_profile("hsbc-uk")


def test_uk_dates_are_day_first():
    # 05/01/25 is 5 January. Reading it month-first would silently move it.
    assert parse_uk_date("05 Jan 25") == date(2025, 1, 5)
    assert parse_uk_date("05/01/25") == date(2025, 1, 5)


def test_type_code_is_the_first_token(profile):
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    assert [t.type_code for t in doc.transactions] == ["DD", "VIS", "CR"]


def test_kerned_summary_labels_are_still_matched(profile):
    """HSBC renders these as "Ope ning Balance" and "£2,000 .00"."""
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    assert doc.opening_balance == 200000
    assert doc.closing_balance == 280000
    assert doc.printed_paid_in == 150000
    assert doc.printed_paid_out == 70000


def test_amount_on_a_continuation_line_belongs_to_the_open_transaction(profile):
    """The code and payee are on one line, the location and amount on the next."""
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    sainsburys = next(t for t in doc.transactions if "SAINSBURYS" in t.description)
    assert sainsburys.amount == 50000
    assert "CAMBRIDGE" in sainsburys.description


def test_period_start_borrows_the_year_from_the_end_date(profile):
    """"30 June to 29 July 2026" prints the year only once."""
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    assert doc.period_start == date(2026, 6, 30)
    assert doc.period_end == date(2026, 7, 29)


def test_account_holders_are_taken_from_the_statement(profile):
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    assert doc.owner == "Philip Edward Howard & Mrs Gina Sue Neff"
    assert doc.account == "****7876"


def test_a_lookalike_code_inside_a_description_is_not_matched(profile):
    """'BP' appearing in a merchant name must not be read as a bill payment —
    the code is the first token or it is not the code."""
    text = uk_statement().replace("SAINSBURYS S/MKTS", "SHELL BP GARAGE")
    doc = parse_statement("uk.pdf", profile, text=text)
    shell = next(t for t in doc.transactions if "SHELL" in t.description)
    assert shell.type_code == "VIS"
    assert shell.amount == 50000


def test_column_position_sets_direction(profile):
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    salary = next(t for t in doc.transactions if t.type_code == "CR")
    assert salary.direction is Direction.IN
    assert salary.amount == 150000


def test_checkpoint_and_boilerplate_excluded(profile):
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    assert len(doc.transactions) == 3
    assert [c.balance for c in doc.checkpoints] == [200000]
    assert not any("Co mpe ns atio n" in t.description for t in doc.transactions)
    assert not any("Inte re s t Rate" in t.description for t in doc.transactions)


def test_statement_reconciles(profile):
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    check = reconcile(doc)
    assert check.ok, check.notes
    assert check.computed_paid_in == 150000
    assert check.computed_paid_out == 70000


def test_card_refund_on_the_paid_in_side_is_read_correctly(profile):
    """A VIS refund uses the same code as the purchase it reverses. Column
    position gets it right and the balance check confirms it."""
    doc = parse_statement("uk.pdf", profile, text=uk_statement(refund_as_purchase=True))
    refund = next(t for t in doc.transactions if "REFUND" in t.description)
    assert refund.direction is Direction.IN

    check = reconcile(doc)
    assert check.ok, check.notes
    # VIS can post either way, so its direction is only ever balance-confirmed.
    assert refund.direction_confidence == "resolved_by_balance"
    assert refund.reconciliation_note == ""


def test_sheet_number_is_captured(profile):
    """It sits after the sortcode and account number, not after a phone number."""
    doc = parse_statement("uk.pdf", profile, text=uk_statement())
    assert doc.sheet_numbers == ["858"]
