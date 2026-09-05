import pytest

from statements.money import format_money, parse_money


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.56", 123456),
        ("1234.56", 123456),
        ("£42.00", 4200),
        ("(89.50)", -8950),
        ("-89.50", -8950),
        ("0.04", 4),
        ("1,168.38", 116838),
    ],
)
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12", "1.234", "12.3"])
def test_parse_money_rejects_non_amounts(raw):
    with pytest.raises(ValueError):
        parse_money(raw)


@pytest.mark.parametrize(
    "minor,expected", [(123456, "1234.56"), (4, "0.04"), (-8950, "-89.50"), (0, "0.00"), (None, "")]
)
def test_format_money(minor, expected):
    assert format_money(minor) == expected


def test_money_round_trips_without_float_drift():
    total = sum(parse_money(v) for v in ["0.10", "0.20", "0.30", "1,234.56"])
    assert format_money(total) == "1235.16"
