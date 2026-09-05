"""Choosing a profile without being told which, and inferring one when none fits."""

import pytest

from statements.detect import MATCH_THRESHOLD, best_match, detect
from statements.infer import InferenceFailed, infer_profile
from statements.layout import split_pages
from statements.profiles import get_profile
from tests.bank.fixtures import card_statement, uk_statement, us_statement


@pytest.mark.parametrize(
    "text,expected",
    [
        (us_statement(), "hsbc-us"),
        (uk_statement(), "hsbc-uk"),
        (card_statement(), "hsbc-uk-card"),
    ],
)
def test_each_layout_is_recognised(text, expected):
    match = best_match(split_pages(text))
    assert match is not None
    assert match.profile.name == expected


def test_the_winner_is_clear_of_the_runner_up():
    """A narrow win would mean the scores are not really discriminating."""
    ranked = detect(split_pages(us_statement()))
    assert ranked[0].score - ranked[1].score > 0.3


def test_an_unrelated_document_matches_nothing():
    pages = split_pages("Dear Sir\nThank you for your enquiry.\nYours faithfully\n")
    assert best_match(pages) is None


def test_scores_are_explainable():
    match = best_match(split_pages(us_statement()))
    assert "summary" in match.explain()
    assert set(match.detail) == {"summary", "table", "codes", "period"}


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #

def test_month_first_dates_are_inferred_as_month_first():
    """03/04 is ambiguous alone; the column as a whole settles it."""
    profile, notes = infer_profile(split_pages(us_statement()))
    assert any("%m/%d" in note for note in notes)


def test_day_first_dates_are_inferred_as_day_first():
    profile, notes = infer_profile(split_pages(uk_statement()))
    assert any("%d %b" in note for note in notes)


def test_the_type_code_column_is_discovered():
    """A code repeats down the column; a merchant's first word rarely does, so
    discovery needs several rows before it will call something a code."""
    from tests.bank.fixtures import uk_row

    rows = [uk_row(f"0{n} Jul 26", "DD", f"UTILITY {n}", "10.00") for n in range(1, 5)]
    rows += [uk_row(f"1{n} Jul 26", "CR", f"SALARY {n}", paid_in="100.00") for n in range(1, 5)]
    _, notes = infer_profile(split_pages("\n".join(rows)))
    codes = next(note for note in notes if note.startswith("type codes"))
    assert "DD" in codes and "CR" in codes


def test_a_short_statement_does_not_invent_a_code_vocabulary():
    """Three rows cannot establish that a token is a code rather than a payee."""
    _, notes = infer_profile(split_pages(uk_statement()))
    assert any("every dated line is a transaction" in note for note in notes)


def test_a_layout_without_codes_is_recognised_as_such():
    _, notes = infer_profile(split_pages(card_statement()))
    assert any("every dated line is a transaction" in note for note in notes)


def test_amount_columns_are_located():
    _, notes = infer_profile(split_pages(us_statement()))
    columns = next(note for note in notes if note.startswith("amount columns"))
    assert "119" in columns or "140" in columns


def test_currency_is_taken_from_the_symbol_used():
    profile, _ = infer_profile(split_pages(uk_statement()))
    assert profile.currency == "GBP"
    profile, _ = infer_profile(split_pages(us_statement()))
    assert profile.currency == "USD"


def test_a_document_with_no_dates_is_refused():
    with pytest.raises(InferenceFailed, match="no transaction table|column of dates"):
        infer_profile(split_pages("Dear Sir\nThank you for your enquiry.\n"))


def test_an_empty_document_says_to_try_ocr():
    with pytest.raises(InferenceFailed, match="scan"):
        infer_profile(split_pages("   \n  \n"))


def test_inferred_profile_is_usable_for_a_trial_run():
    """It need not reconcile — the gate decides that — but it must parse."""
    from statements.parse import parse_statement

    profile, _ = infer_profile(split_pages(us_statement()))
    doc = parse_statement("x.pdf", profile, text=us_statement())
    assert doc.transactions
