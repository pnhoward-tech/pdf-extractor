"""Corroborating dates against everything else the document says about them."""

from datetime import date

import pytest

from statements.dateevidence import (
    assess_period,
    dates_from_filename,
    day_count,
    repair_by_sequence,
    swap_day_month,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("20250206_Statement.pdf", date(2025, 2, 6)),
        ("Statement 2025-02-06.pdf", date(2025, 2, 6)),
        ("statement_2025_02_06.pdf", date(2025, 2, 6)),
        # Month-first is tried first: these names come from US banking systems.
        ("DDA_Rendered_Statement__1_11_2024__Account__1.pdf", date(2024, 1, 11)),
    ],
)
def test_the_date_a_file_name_states(name, expected):
    assert dates_from_filename(name)[0] == expected


def test_an_ambiguous_file_name_offers_both_readings():
    """1_11_2024 is 11 January or 1 November; the document decides."""
    assert dates_from_filename("x_1_11_2024.pdf") == [date(2024, 1, 11), date(2024, 11, 1)]


def test_an_unambiguous_name_offers_only_one():
    assert dates_from_filename("x_1_14_2026.pdf") == [date(2026, 1, 14)]


def test_a_name_with_no_date_offers_nothing():
    assert dates_from_filename("statement.pdf") == []


def test_an_impossible_date_in_a_name_is_ignored():
    assert dates_from_filename("13_45_2024.pdf") == []


def test_the_printed_day_count_is_read():
    assert day_count("01/11/2024 Ending Balance 29 Days in Statement Period 1,614.62") == 29
    assert day_count("nothing here") is None


# --------------------------------------------------------------------------- #
# Weighing the period
# --------------------------------------------------------------------------- #

def test_a_period_the_file_name_agrees_with_is_corroborated():
    result = assess_period(
        date(2025, 1, 7), date(2025, 2, 6), filename="20250206_Statement.pdf"
    )
    assert result.corroborated
    assert not result.repaired
    assert result.notes == []


def test_a_backwards_period_is_rebuilt_from_the_end_and_the_span():
    """A scan read 2023 as 2025. The end date and the printed span both survive,
    and together they say exactly what the start must have been."""
    result = assess_period(
        date(2025, 12, 14),
        date(2024, 1, 11),
        filename="DDA_Rendered_Statement__1_11_2024__x.pdf",
        span=29,
    )
    assert result.repaired
    assert result.start == date(2023, 12, 14)
    assert result.end == date(2024, 1, 11)
    assert any("rebuilt as 2023-12-14" in n for n in result.notes)


def test_a_backwards_period_with_nothing_to_check_it_against_is_only_reported():
    result = assess_period(date(2025, 12, 14), date(2024, 1, 11))
    assert not result.repaired
    assert result.start == date(2025, 12, 14)  # left alone, not guessed at
    assert any("runs backwards" in n for n in result.notes)


def test_a_missing_end_date_is_taken_from_the_file_name():
    result = assess_period(None, None, filename="20250206_Statement.pdf")
    assert result.end == date(2025, 2, 6)
    assert result.repaired


def test_a_span_that_contradicts_the_printed_period_is_reported():
    result = assess_period(date(2025, 1, 1), date(2025, 1, 31), span=99)
    assert any("says 99 days" in n for n in result.notes)
    assert result.start == date(2025, 1, 1)  # reported, not overruled


def test_evidence_is_listed_for_the_reader():
    result = assess_period(
        date(2025, 1, 7), date(2025, 2, 6),
        filename="20250206_Statement.pdf", span=31, period_mentions=8,
    )
    assert {e.source for e in result.evidence} == {"filename", "day count", "repetition"}


# --------------------------------------------------------------------------- #
# Sequence
# --------------------------------------------------------------------------- #

def test_swapping_day_and_month():
    assert swap_day_month(date(2025, 4, 3)) == date(2025, 3, 4)
    assert swap_day_month(date(2025, 4, 25)) is None  # no 25th month


def test_a_date_that_breaks_the_run_is_re_read_when_the_swap_fits():
    dates = [date(2025, 3, 1), date(2025, 4, 3), date(2025, 3, 10)]
    #                                    ^ printed 03/04, read month-first
    repairs = repair_by_sequence(dates, date(2025, 3, 1), date(2025, 3, 31))
    assert len(repairs) == 1
    index, corrected, why = repairs[0]
    assert index == 1 and corrected == date(2025, 3, 4)
    assert "read as 2025-03-04" in why


def test_a_date_that_fits_the_run_is_left_alone():
    dates = [date(2025, 3, 1), date(2025, 3, 4), date(2025, 3, 10)]
    assert repair_by_sequence(dates, date(2025, 3, 1), date(2025, 3, 31)) == []


def test_a_swap_that_lands_outside_the_period_is_refused():
    dates = [date(2025, 3, 1), date(2025, 9, 2), date(2025, 3, 10)]
    # Swapping gives 2025-02-09, before the period; not a supported reading.
    assert repair_by_sequence(dates, date(2025, 3, 1), date(2025, 3, 31)) == []


def test_a_swap_that_does_not_restore_the_run_is_refused():
    dates = [date(2025, 3, 20), date(2025, 1, 2), date(2025, 3, 25)]
    # 02/01 swapped is 2025-02-01, still before 2025-03-20.
    assert repair_by_sequence(dates, date(2025, 1, 1), date(2025, 12, 31)) == []
