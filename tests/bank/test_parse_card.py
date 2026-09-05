"""HSBC UK credit card: two dates, a pre-signed amount column, and a balance
that money *out* increases."""

from datetime import date

import pytest

from statements.parse import parse_statement
from statements.profiles import Direction, get_profile
from statements.reconcile import reconcile
from tests.bank.fixtures import card_statement


@pytest.fixture
def profile():
    return get_profile("hsbc-uk-card")


@pytest.fixture
def doc(profile):
    return parse_statement("card.pdf", profile, text=card_statement())


def test_summary_box_read_despite_hsbc_kerning(doc):
    """'Credit Lim it' is split mid-word in HSBC's own PDF; the fields we need
    must be matched without relying on the broken ones."""
    assert doc.opening_balance == 100000
    assert doc.closing_balance == 119000
    assert doc.printed_paid_out == 25000
    assert doc.printed_paid_in == 6000


def test_a_leading_date_pair_opens_a_transaction(doc):
    """There is no code column: the dates are what mark a new transaction."""
    assert len(doc.transactions) == 8


def test_transaction_and_posting_dates_are_kept_apart(doc):
    """'13 Apr 24  11 Apr 24' means received on the 13th, transacted on the 11th."""
    row = next(t for t in doc.transactions if "INFOGRAPHICA" in t.description)
    assert row.txn_date == date(2024, 4, 11)
    assert row.posting_date == date(2024, 4, 13)


def test_cr_suffix_marks_money_in(doc):
    refund = next(t for t in doc.transactions if "UNIQLO" in t.description)
    payment = next(t for t in doc.transactions if "DIRECT DEBIT" in t.description)
    assert refund.direction is Direction.IN and refund.amount == 5000
    assert payment.direction is Direction.IN and payment.amount == 1000
    assert refund.direction_confidence == "certain"  # the bank stated it outright


def test_unsuffixed_amounts_are_money_out(doc):
    netflix = next(t for t in doc.transactions if "Netflix" in t.description)
    assert netflix.direction is Direction.OUT
    assert netflix.type_code == "PUR"


def test_columns_shifting_between_sheets_are_handled(doc):
    """Sheet 3's amount column sits 27 characters right of sheet 2's."""
    sheet3 = [t for t in doc.transactions if t.page_number == 3]
    assert len(sheet3) == 3
    assert next(t for t in sheet3 if "Coffee Bar" in t.description).amount == 10820


def test_contactless_prefix_is_captured_as_the_code(doc):
    coffee = next(t for t in doc.transactions if "Coffee Bar" in t.description)
    assert coffee.type_code == ")))"


def test_exchange_rate_line_is_folded_in_not_treated_as_an_amount(doc):
    """'7.70 USD@1.2727' is description detail; 6.05 is the sterling amount."""
    google = next(t for t in doc.transactions if "Google" in t.description)
    assert google.amount == 605
    assert google.foreign_amount == 770
    assert google.foreign_currency == "USD"


def test_interest_is_charged_as_a_transaction(doc):
    """The Debits total includes interest, so missing it leaves the statement
    short by exactly that amount."""
    interest = next(t for t in doc.transactions if t.type_code == "TOTAL INTEREST CHARGED")
    assert interest.amount == 1758
    assert interest.direction is Direction.OUT


def test_the_interest_breakdown_is_not_double_counted(doc):
    """The per-rate line above the total states the same 17.58."""
    assert sum(1 for t in doc.transactions if t.amount == 1758) == 1
    assert not any("Estimated interest" in t.description for t in doc.transactions)


def test_statement_reconciles_as_a_liability(doc, profile):
    """opening + out - in == closing, because the balance is what is owed."""
    check = reconcile(doc, liability=profile.is_liability)
    assert check.ok, check.notes
    assert check.computed_paid_out == 25000
    assert check.computed_paid_in == 6000


def test_treating_a_card_as_a_deposit_account_fails_the_check(doc, profile):
    """Guards the sign convention: the wrong one must not quietly pass."""
    check = reconcile(doc, liability=False)
    assert not check.ok


def test_card_number_is_not_carried_in_full(doc):
    assert doc.account == ""  # no full PAN in the fixture; never stored in full


def test_period_end_is_the_statement_date_and_start_is_left_blank(doc):
    assert doc.period_end == date(2024, 4, 16)
    assert doc.period_start is None
