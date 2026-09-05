"""Cross-account duplicates, and checking the dates came out right."""

from datetime import date

import pytest

from statements.dates import check_dates, is_ambiguous
from statements.dedupe import annotate, find_duplicates, similarity
from statements.parse import StatementDoc, Transaction
from statements.profiles import Direction


def txn(amount, day, description, account, currency="GBP", posting=None):
    return Transaction(
        source_file=f"{account}.pdf", page_number=1, line_number=1,
        txn_date=date(2025, 1, day), posting_date=posting, type_code="VIS",
        description=description, amount=amount, direction=Direction.OUT,
        direction_certain=True, currency=currency, source_account=account,
    )


# --------------------------------------------------------------------------- #
# Duplicates
# --------------------------------------------------------------------------- #

def test_same_amount_and_day_in_two_accounts_is_flagged():
    """A card purchase settled by direct debit appears in both places, and the
    two banks describe it completely differently."""
    rows = [txn(12500, 10, "TESCO STORES OXFORD", "CARD1"),
            txn(12500, 10, "PAYMENT TO HSBC CARD", "CUR1")]
    groups = annotate(rows)
    assert len(groups) == 1
    assert all(r.duplicate_group for r in rows)
    assert rows[0].duplicate_of == "CUR1"
    assert rows[1].duplicate_of == "CARD1"


def test_similar_descriptions_within_the_window_match():
    rows = [txn(9900, 10, "NETFLIX.COM LOS GATOS", "CARD1"),
            txn(9900, 13, "NETFLIX COM  LOS GATOS", "CUR1")]
    assert len(find_duplicates(rows)) == 1


def test_matches_outside_the_window_are_not_flagged():
    rows = [txn(9900, 1, "NETFLIX.COM", "CARD1"), txn(9900, 25, "NETFLIX.COM", "CUR1")]
    assert find_duplicates(rows) == []


def test_two_purchases_on_one_account_are_not_duplicates():
    """Buying the same coffee twice is not a double count."""
    rows = [txn(350, 10, "CAFE NERO", "CARD1"), txn(350, 10, "CAFE NERO", "CARD1")]
    assert find_duplicates(rows) == []


def test_different_amounts_never_match():
    rows = [txn(12500, 10, "TESCO", "CARD1"), txn(12501, 10, "TESCO", "CUR1")]
    assert find_duplicates(rows) == []


def test_different_currencies_never_match():
    rows = [txn(12500, 10, "TESCO", "CARD1", currency="GBP"),
            txn(12500, 10, "TESCO", "CUR1", currency="USD")]
    assert find_duplicates(rows) == []


def test_nothing_is_removed_only_tagged():
    rows = [txn(12500, 10, "TESCO", "CARD1"), txn(12500, 10, "TESCO PAYMENT", "CUR1")]
    annotate(rows)
    assert len(rows) == 2  # both kept; which to drop is the reader's call


def test_company_suffixes_do_not_defeat_matching():
    assert similarity("MARKS & SPENCER PLC", "Marks and Spencer Ltd") > 0.6


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value,expected", [
    (date(2025, 4, 3), True),    # 3 April or 4 March
    (date(2025, 12, 25), False),  # 25 cannot be a month
    (date(2025, 4, 4), False),    # identical either way round
])
def test_ambiguity_detection(value, expected):
    assert is_ambiguous(value) is expected


def _doc(transactions, start=date(2025, 1, 1), end=date(2025, 1, 31)):
    return StatementDoc(source_file="s.pdf", profile="p", currency="GBP",
                        period_start=start, period_end=end, transactions=transactions)


def test_dates_inside_the_period_and_in_order_are_certain():
    rows = [txn(100, 5, "A", "X"), txn(100, 10, "B", "X"), txn(100, 20, "C", "X")]
    report = check_dates(_doc(rows))
    assert report.ok
    assert {r.date_confidence for r in rows} == {"certain"}


def test_a_date_outside_the_period_is_flagged():
    rows = [txn(100, 5, "A", "X")]
    rows[0].txn_date = date(2023, 6, 1)
    report = check_dates(_doc(rows))
    assert not report.ok
    assert rows[0].date_confidence == "outside_period"


def test_a_badly_ordered_column_suggests_a_swapped_day_and_month():
    days = [28, 2, 27, 3, 26, 4, 25, 5, 24, 6]
    rows = [txn(100, d, f"row{i}", "X") for i, d in enumerate(days)]
    report = check_dates(_doc(rows))
    assert any("out of date order" in n for n in report.notes)
    assert {r.date_confidence for r in rows} == {"order_suspect"}


def test_ordering_is_judged_on_the_posting_date_where_there_is_one():
    """A card lists by when the bank received it, so its transaction dates
    legitimately jump around."""
    rows = [
        txn(100, 3, "a", "X", posting=date(2025, 1, 5)),
        txn(100, 1, "b", "X", posting=date(2025, 1, 6)),
        txn(100, 8, "c", "X", posting=date(2025, 1, 9)),
        txn(100, 2, "d", "X", posting=date(2025, 1, 10)),
        txn(100, 15, "e", "X", posting=date(2025, 1, 16)),
        txn(100, 4, "f", "X", posting=date(2025, 1, 17)),
        txn(100, 20, "g", "X", posting=date(2025, 1, 21)),
        txn(100, 9, "h", "X", posting=date(2025, 1, 22)),
    ]
    assert check_dates(_doc(rows)).ok


def test_a_section_organised_statement_is_not_expected_to_be_chronological():
    days = [28, 2, 27, 3, 26, 4, 25, 5, 24, 6]
    rows = [txn(100, d, f"row{i}", "X") for i, d in enumerate(days)]
    assert check_dates(_doc(rows), chronological=False).ok


def test_one_row_out_of_order_in_a_tiny_statement_proves_nothing():
    rows = [txn(100, 12, "a", "X"), txn(100, 6, "b", "X"), txn(100, 12, "c", "X")]
    assert check_dates(_doc(rows)).ok


def test_a_backwards_period_is_reported():
    report = check_dates(_doc([], start=date(2025, 12, 14), end=date(2024, 1, 11)))
    assert any("runs backwards" in n for n in report.notes)
