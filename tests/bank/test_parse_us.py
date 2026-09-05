"""HSBC US parsing, against layout text shaped like the real statements."""

from datetime import date

import pytest

from statements.parse import parse_statement
from statements.profiles import Direction, get_profile
from tests.bank.fixtures import us_multiline_statement, us_statement


@pytest.fixture
def profile():
    return get_profile("hsbc-us")


@pytest.fixture
def doc(profile):
    return parse_statement("stmt.pdf", profile, text=us_statement())


def test_summary_box_is_read_as_ground_truth(doc):
    assert doc.opening_balance == 100000
    assert doc.closing_balance == 107004
    assert doc.printed_paid_in == 25004
    assert doc.printed_paid_out == 18000


def test_statement_period_parsed_month_first(doc):
    # 01/07/25 is 7 January, not 1 July — day/month must not silently swap.
    assert doc.period_start == date(2025, 1, 7)
    assert doc.period_end == date(2025, 2, 6)


def test_account_number_captured(doc):
    assert doc.account == "446-084310"


def test_all_transactions_found_across_both_pages(doc):
    assert len(doc.transactions) == 5
    assert {t.page_number for t in doc.transactions} == {1, 2}


def test_page_two_column_shift_is_handled(doc):
    """Page 2's amounts sit 22 characters left of page 1's. A single hardcoded
    threshold would put page 2's withdrawals in the deposits column."""
    page2 = [t for t in doc.transactions if t.page_number == 2]
    purchase = next(t for t in page2 if "CAFE MILANO" in t.description)
    assert purchase.direction is Direction.OUT
    assert purchase.amount == 8000


def test_balance_is_the_currency_marked_amount(doc):
    first = doc.transactions[0]
    assert first.amount == 4000
    assert first.printed_balance == 96000


def test_date_carries_forward_to_lines_that_omit_it(doc):
    dated, undated = doc.transactions[0], doc.transactions[1]
    assert dated.txn_date == date(2025, 1, 8)
    assert undated.txn_date == date(2025, 1, 8)


def test_trailing_continuation_line_joins_its_transaction(doc):
    first = doc.transactions[0]
    assert first.description.endswith("GB")
    assert "GB" not in doc.transactions[1].description.split()[0]


def test_numbers_in_the_description_are_not_the_amount(doc):
    """'EUR 45.00 RATE 1.1523' sits in the description columns; the transaction
    amount is 80.00, further right."""
    purchase = next(t for t in doc.transactions if "CAFE MILANO" in t.description)
    assert purchase.amount == 8000
    assert purchase.foreign_amount == 4500
    assert purchase.foreign_currency == "EUR"


def test_checkpoints_are_not_transactions(doc):
    assert all("BALANCE" not in t.type_code for t in doc.transactions)
    assert [c.balance for c in doc.checkpoints] == [100000, 107004]


def test_interest_is_money_in(doc):
    interest = next(t for t in doc.transactions if t.type_code == "INTEREST PAID")
    assert interest.direction is Direction.IN
    assert interest.signed == -4  # negative = money in, per the workbook convention


def test_boilerplate_after_the_table_is_not_parsed(doc):
    assert not any("deposited items" in t.description.lower() for t in doc.transactions)
    assert not any("Page" in t.description for t in doc.transactions)


def test_multi_line_transaction_finds_its_amount(profile):
    """A wire whose amount is three lines below its description."""
    doc = parse_statement("wire.pdf", profile, text=us_multiline_statement())
    assert len(doc.transactions) == 1
    wire = doc.transactions[0]
    assert wire.amount == 50000
    assert "ACME LTD" in wire.description
    assert wire.foreign_currency == "EUR"
    assert not doc.warnings
