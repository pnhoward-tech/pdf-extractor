"""OCR support: rebuilding layout text from word boxes, and the digit repair."""

import pytest

from statements.ocr import repair_numeric_token, words_to_layout

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv(*words: tuple[int, int, int, str]) -> str:
    """Build tesseract TSV from (line, left, width, text) tuples."""
    rows = [HEADER]
    for index, (line, left, width, text) in enumerate(words):
        rows.append(f"5\t1\t1\t1\t{line}\t{index}\t{left}\t{line * 20}\t{width}\t12\t96\t{text}")
    return "\n".join(rows)


def test_words_are_placed_at_their_scaled_columns():
    """Pixel positions become character columns, which is what lets the parser's
    column logic work on a scan at all."""
    layout = words_to_layout(
        tsv((1, 0, 100, "OPENING"), (1, 800, 100, "1,614.62")), width=100
    )
    line = layout.split("\n")[0]
    assert line.startswith("OPENING")
    assert line.rstrip().endswith("1,614.62")
    assert line.index("1,614.62") > 50


def test_words_on_the_same_line_stay_on_one_line():
    layout = words_to_layout(tsv((1, 0, 50, "A"), (1, 100, 50, "B"), (2, 0, 50, "C")))
    assert len(layout.split("\n")) == 2


def test_overlapping_words_are_kept_separate():
    """After scaling, two words can land on the same column; they must not be
    run together into one token."""
    layout = words_to_layout(tsv((1, 0, 900, "FIRST"), (1, 901, 90, "SECOND")), width=20)
    assert "FIRSTSECOND" not in layout


def test_low_confidence_rows_are_dropped():
    rows = tsv((1, 0, 50, "GOOD")).split("\n")
    rows.append("5\t1\t1\t1\t1\t9\t100\t20\t50\t12\t-1\tJUNK")
    assert "JUNK" not in words_to_layout("\n".join(rows))


def test_empty_input_is_not_an_error():
    assert words_to_layout(HEADER) == ""


@pytest.mark.parametrize(
    "raw,expected",
    [
        (".O0", ".00"),
        (".o0", ".00"),
        ("O1/11/2024", "01/11/2024"),
        ("l,6l4.62", "1,614.62"),
    ],
)
def test_digit_lookalikes_are_repaired_inside_numeric_tokens(raw, expected):
    assert repair_numeric_token(raw) == expected


@pytest.mark.parametrize("word", ["GINA", "NEFF", "SLOPE", "SO", "DEPOSIT", "LEXINGTON"])
def test_words_are_never_mangled_into_digits(word):
    assert repair_numeric_token(word) == word


def test_a_digit_misread_as_another_digit_cannot_be_repaired():
    """2023 scanned as 2025 is indistinguishable from correct input. This is why
    OCR output still needs the period check and a spot-check of dates."""
    assert repair_numeric_token("12/14/2025") == "12/14/2025"
