import pytest

from app.mapping import (
    Profile,
    choose_profile,
    load_profiles,
    match_columns,
    similarity,
    to_date,
    to_number,
)


@pytest.fixture
def profiles():
    return load_profiles()


def test_bundled_profiles_load(profiles):
    assert {p.name for p in profiles} >= {"invoice", "statement"}


@pytest.mark.parametrize(
    "header,column,expected_min",
    [
        ("Amount (USD)", "amount", 0.85),
        ("Qty", "quantity", 0.75),
        ("Transaction Date", "date", 0.85),
        ("Description of Work", "description", 0.85),
    ],
)
def test_header_variants_match_their_column(header, column, expected_min):
    assert similarity(header, column) >= expected_min


def test_unrelated_headers_do_not_match():
    assert similarity("Sensor ID", "amount") < 0.5
    assert similarity("Calibrated By", "date") < 0.5


def test_match_columns_never_reuses_a_source_column(profiles):
    invoice = next(p for p in profiles if p.name == "invoice")
    header = ["Description", "Qty", "Unit Price", "Total"]
    mapping = match_columns(header, invoice)
    used = [i for i in mapping.values() if i is not None]
    assert len(used) == len(set(used))
    assert mapping["description"] == 0
    assert mapping["quantity"] == 1


def test_choose_profile_picks_the_right_one(profiles):
    header = ["Transaction Date", "Details", "Money Out", "Money In", "Balance"]
    profile, score = choose_profile(header, "statement of account balance", profiles)
    assert profile.name == "statement"
    assert score > 0.5


def test_choose_profile_returns_none_for_unrelated_tables(profiles):
    profile, score = choose_profile(["Sensor ID", "Reading", "Calibrated By"], "site survey", profiles)
    assert profile is None
    assert score == 0.0


def test_required_column_missing_disqualifies_profile():
    profile = Profile.from_dict(
        {"columns": [{"name": "date", "required": True}, {"name": "amount"}]}, "t"
    )
    assert choose_profile(["Amount", "Notes"], "", [profile]) == (None, 0.0)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.56", "1234.56"),
        ("(89.50)", "-89.5"),
        ("1.234,56", "1234.56"),
        ("£42", "42"),
        ("2,500.00", "2500"),
        ("", ""),
        ("n/a", "n/a"),
    ],
)
def test_number_normalisation(raw, expected):
    assert to_number(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01/03/2024", "2024-03-01"),
        ("2024-03-01", "2024-03-01"),
        ("3 March 2024", "2024-03-03"),
        ("Mar 3, 2024", "2024-03-03"),
        ("not a date", "not a date"),
    ],
)
def test_date_normalisation(raw, expected):
    assert to_date(raw) == expected
