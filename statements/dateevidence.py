"""Corroborating dates from everything the document says about them.

A statement states its dates several times over: in the period line, once per
page; in a printed count of days; in the sequence the transactions are listed
in; and very often in the file's own name. Any one of them can be misread — a
scan turns 2023 into 2025, a bank writes 03/04 and means either — but they are
unlikely to be misread the same way at once.

Nothing here rewrites an amount, and it repairs a date only where two
independent sources agree on the correction. Everything else is reported, not
fixed, and every repair is recorded in the statement's notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# "29 Days in Statement Period" — an exact span, counted inclusively.
DAY_COUNT_RE = re.compile(r"(\d{1,3})\s*Days?\s+in\s+Statement\s+Period", re.I)

# Date shapes that turn up in file names.
FILENAME_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(20\d{2})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{1,2})[-_.](\d{1,2})[-_.](20\d{2})(?!\d)"), "dmy_or_mdy"),
]


@dataclass
class Evidence:
    """One thing the document says about its dates."""

    source: str
    detail: str
    dates: list[date] = field(default_factory=list)


@dataclass
class PeriodAssessment:
    start: date | None
    end: date | None
    repaired: bool = False
    corroborated: bool = False
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def dates_from_filename(name: str) -> list[date]:
    """Every date a file name could be stating, most confident first.

    `20250206_Statement.pdf` is unambiguous. `1_11_2024` is not — it is
    11 January or 1 November depending on where the bank is — so both readings
    come back and the document decides between them.
    """
    found: list[date] = []
    for pattern, shape in FILENAME_PATTERNS:
        for match in pattern.finditer(name):
            groups = [int(g) for g in match.groups()]
            if shape == "ymd":
                year, month, day = groups
                found.extend(_safe(year, month, day))
            else:
                first, second, year = groups
                # Month-first and day-first, in that order: these file names are
                # usually written by the bank's own US-facing systems.
                found.extend(_safe(year, first, second))
                found.extend(_safe(year, second, first))
    # Keep order, drop repeats.
    return list(dict.fromkeys(found))


def _safe(year: int, month: int, day: int) -> list[date]:
    try:
        return [date(year, month, day)]
    except ValueError:
        return []


def day_count(text: str) -> int | None:
    """The span the statement says it covers, if it says."""
    match = DAY_COUNT_RE.search(text)
    return int(match.group(1)) if match else None


def assess_period(
    start: date | None,
    end: date | None,
    *,
    filename: str = "",
    span: int | None = None,
    period_mentions: int = 0,
) -> PeriodAssessment:
    """Weigh what the document says about its own period against itself."""
    assessment = PeriodAssessment(start=start, end=end)
    filename_dates = dates_from_filename(filename)

    if filename_dates:
        assessment.evidence.append(
            Evidence("filename", f"{filename} suggests {filename_dates[0]}", filename_dates)
        )
    if span:
        assessment.evidence.append(Evidence("day count", f"{span} days in the period"))
    if period_mentions > 1:
        assessment.evidence.append(
            Evidence("repetition", f"the period line appears on {period_mentions} pages")
        )

    # The end date is the one a file name almost always carries.
    if end and end in filename_dates:
        assessment.corroborated = True
    elif end is None and filename_dates:
        assessment.end = end = filename_dates[0]
        assessment.repaired = True
        assessment.notes.append(
            f"Statement period end not printed; taken from the file name ({end})."
        )

    if start and end and start <= end:
        # Where a span is printed too, check the two agree.
        if span and (end - start).days != span - 1:
            assessment.notes.append(
                f"The statement says {span} days but its printed period spans "
                f"{(end - start).days + 1}."
            )
        return assessment

    # The period is impossible or incomplete. Rebuild the start from the end
    # and the printed span, which is the case a misread year produces.
    if end and span:
        rebuilt = end - timedelta(days=span - 1)
        if rebuilt != start:
            reason = (
                "was after the end date" if start and start > end else "was not printed"
            )
            assessment.notes.append(
                f"Statement period start {reason}"
                + (f" ({start})" if start else "")
                + f"; rebuilt as {rebuilt} from the end date and the printed "
                f"{span}-day span."
            )
            assessment.start = rebuilt
            assessment.repaired = True
    elif start and end and start > end:
        assessment.notes.append(
            f"Statement period runs backwards ({start} to {end}) and nothing in "
            "the document settles which date is wrong."
        )
    return assessment


def swap_day_month(value: date) -> date | None:
    """The other reading of the same digits, where there is one."""
    try:
        return date(value.year, value.day, value.month)
    except ValueError:
        return None


def repair_by_sequence(
    dates: list[date | None], low: date | None, high: date | None
) -> list[tuple[int, date, str]]:
    """Find dates whose day/month swap is the only reading that fits.

    Statements list transactions in order. Where one date breaks that order and
    swapping its day and month both restores the order and lands inside the
    period, the swap is the reading the document supports — a stronger claim
    than either the sequence or the period could make alone.
    """
    repairs: list[tuple[int, date, str]] = []
    for index, value in enumerate(dates):
        if value is None:
            continue
        before = _previous(dates, index)
        after = _next(dates, index)
        if _in_order(before, value, after):
            continue
        swapped = swap_day_month(value)
        if swapped is None or swapped == value:
            continue
        if not _in_order(before, swapped, after):
            continue
        if low and high and not (low <= swapped <= high):
            continue
        repairs.append(
            (index, swapped, f"{value} breaks the run {before}..{after}; read as {swapped}")
        )
    return repairs


def _previous(dates: list[date | None], index: int) -> date | None:
    for value in reversed(dates[:index]):
        if value is not None:
            return value
    return None


def _next(dates: list[date | None], index: int) -> date | None:
    for value in dates[index + 1 :]:
        if value is not None:
            return value
    return None


def _in_order(before: date | None, value: date, after: date | None) -> bool:
    if before and value < before:
        return False
    if after and value > after:
        return False
    return True
