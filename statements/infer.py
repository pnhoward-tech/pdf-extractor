"""Reading an unfamiliar statement without a profile written for it.

A profile is a description of a layout, and a statement mostly describes its own
layout: the transaction lines sit in a column-aligned block, the amounts cluster
into columns, the codes repeat, and the summary box uses one of a small set of
wordings. This module reads those properties off the document and returns a
Profile built from them.

An inferred profile is a starting point, not a verdict. Everything it produces
still goes through the same reconciliation gate, which is what makes it safe to
try: if the inference is wrong, the statement does not balance and its rows are
held back rather than shipped.

`python -m statements.cli learn statement.pdf` prints one as a module ready to
be saved into `statements/profiles/` and refined.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

from .layout import Line, Page
from .profiles import Direction, Profile, TypeCode

# Date shapes worth trying, most specific first. Each entry is a regex for the
# token and the strptime formats that could explain it.
DATE_SHAPES: list[tuple[str, tuple[str, ...]]] = [
    (r"\d{4}-\d{2}-\d{2}", ("%Y-%m-%d",)),
    (r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", ("%d %b %Y", "%d %B %Y")),
    (r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2}", ("%d %b %y", "%d %B %y")),
    (r"\d{2}/\d{2}/\d{4}", ("%m/%d/%Y", "%d/%m/%Y")),
    (r"\d{2}/\d{2}/\d{2}", ("%m/%d/%y", "%d/%m/%y")),
    (r"\d{2}-\d{2}-\d{4}", ("%d-%m-%Y", "%m-%d-%Y")),
]

# Wordings banks use for the four summary figures. Order matters only in that
# the first match wins.
SUMMARY_WORDINGS: dict[str, tuple[str, ...]] = {
    "opening_balance": ("opening balance", "beginning balance", "previous balance",
                        "balance brought forward", "starting balance"),
    "closing_balance": ("closing balance", "ending balance", "new balance",
                        "balance carried forward", "final balance"),
    "printed_paid_in": ("payments in", "total paid in", "deposits", "credits",
                        "total credits", "money in"),
    "printed_paid_out": ("payments out", "total paid out", "withdrawals", "debits",
                         "total debits", "money out"),
}

AMOUNT_LABEL = re.compile(r"([A-Za-z][A-Za-z /&'-]{3,40}?)\s*[:+-]?\s*[$£€]?\s*([\d, ]+\.\s?\d{2})")


class InferenceFailed(RuntimeError):
    """The document does not look like a transaction statement."""


def infer_profile(pages: list[Page], name: str = "inferred") -> tuple[Profile, list[str]]:
    """Build a Profile from the document itself. Returns it with a plain-English
    account of what was inferred, which the caller should show the user."""
    lines = [line for page in pages for line in page.lines if line.stripped]
    if not lines:
        raise InferenceFailed("The PDF has no text. If it is a scan, use --ocr.")

    shape, formats, dated = _detect_date_shape(lines)
    if not dated:
        raise InferenceFailed(
            "No column of dates found, so there is no transaction table to read."
        )

    date_format = _choose_date_format(dated, formats)
    # Cluster amounts over the whole span the table covers, not just the lines
    # that start with a date: a running balance is often printed once per day
    # group, on a line that carries no date of its own.
    columns = _amount_columns(_table_span(pages, dated), len(dated))
    if not columns:
        raise InferenceFailed("Found dates but no aligned column of amounts.")

    header = _header_line(pages, dated)
    codes = _infer_codes(dated, shape)
    summary = _infer_summary(lines)

    notes = [
        f"date format {date_format} (from {len(dated)} dated lines)",
        f"amount columns at {columns}",
        f"table header {header!r}" if header else "no column header found",
        f"type codes {sorted(c.code for c in codes) or 'none — every dated line is a transaction'}",
        f"summary fields {sorted(summary) or 'none — the statement cannot be reconciled'}",
    ]

    balance_col = columns[-1] if len(columns) >= 2 else None
    profile = Profile(
        name=name,
        bank="unknown",
        description=f"inferred from the document ({date_format})",
        currency=_infer_currency(lines),
        # Anchored on the header's first few words, space-tolerantly: PDF
        # kerning makes the full string unreliable, and continuation pages
        # often reprint only part of it.
        table_start=[re.compile(_header_anchor(header), re.I)] if header
        else [re.compile(r"^", re.M)],
        table_stop=[re.compile(p, re.I) for p in _infer_stops(pages, dated)],
        summary_patterns=summary,
        date_pattern=re.compile(rf"^\s*({shape})\s"),
        parse_date=_date_parser(date_format),
        date_starts_transaction=not codes,
        code_source="first_token",
        codes=tuple(codes),
        default_code="TXN",
        balance_marker="column" if balance_col else "none",
        description_max_col=max(20, min(columns) - 25),
        amount_band_width=60,
        balance_min_col=balance_col - 1 if balance_col else 999,
        default_in_out_split=columns[0] if len(columns) >= 3 else 0,
        paid_in_side="left",
        checkpoint_patterns=[re.compile(r"balance (brought|carried) forward", re.I)],
        noise_patterns=[re.compile(r"^\s*page \d+ of \d+\s*$", re.I)],
    )
    return profile, notes


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

def _detect_date_shape(lines: list[Line]) -> tuple[str, tuple[str, ...], list[Line]]:
    """The date shape that opens the most lines — those lines are the table."""
    best: tuple[int, str, tuple[str, ...], list[Line]] = (0, "", (), [])
    for shape, formats in DATE_SHAPES:
        pattern = re.compile(rf"^\s*({shape})\s")
        matched = [line for line in lines if pattern.match(line.text)]
        if len(matched) > best[0]:
            best = (len(matched), shape, formats, matched)
    # A handful of stray dates is a letterhead, not a table.
    if best[0] < 3:
        return "", (), []
    return best[1], best[2], best[3]


def _choose_date_format(dated: list[Line], formats: tuple[str, ...]) -> str:
    """Decide between readings like MM/DD and DD/MM.

    Day-first and month-first are indistinguishable on 03/04 alone, so the
    choice is made on the whole column: a format that parses every date wins,
    and where both do, the one whose dates run in order wins — statements list
    transactions chronologically.
    """
    tokens = [re.match(r"^\s*(\S+(?:\s+\S+){0,2})", line.text).group(1).strip()
              for line in dated]
    scored: list[tuple[int, int, str]] = []
    for fmt in formats:
        parsed = []
        for token in tokens:
            try:
                parsed.append(datetime.strptime(_trim(token, fmt), fmt).date())
            except ValueError:
                pass
        if len(parsed) < len(tokens) * 0.8:
            continue  # this format cannot explain the column
        ordered = sum(1 for a, b in zip(parsed, parsed[1:]) if a <= b)
        scored.append((len(parsed), ordered, fmt))
    if not scored:
        return formats[0]
    scored.sort(key=lambda s: (-s[0], -s[1]))
    return scored[0][2]


def _trim(token: str, fmt: str) -> str:
    """Keep only as many whitespace-separated parts as the format expects."""
    return " ".join(token.split()[: len(fmt.split())])


def _date_parser(fmt: str):
    def parse(text: str) -> date:
        return datetime.strptime(" ".join(text.split()), fmt).date()

    return parse


# --------------------------------------------------------------------------- #
# Columns, codes, boilerplate
# --------------------------------------------------------------------------- #

def _table_span(pages: list[Page], dated: list[Line]) -> list[Line]:
    """Every line between the first and last dated line, inclusive."""
    first, last = dated[0], dated[-1]
    span: list[Line] = []
    for page in pages:
        if not (first.page <= page.number <= last.page):
            continue
        start = first.number if page.number == first.page else 0
        stop = last.number + 1 if page.number == last.page else len(page.lines)
        span.extend(line for line in page.lines[start:stop] if line.stripped)
    return span


def _amount_columns(span: list[Line], dated_count: int, tolerance: int = 3) -> list[int]:
    """Cluster the end positions of amounts into columns."""
    ends = Counter()
    for line in span:
        for amount in line.amounts:
            ends[amount.end_col] += 1
    if not ends:
        return []
    clusters: list[list[int]] = []
    for column in sorted(ends):
        if clusters and column - clusters[-1][-1] <= tolerance:
            clusters[-1].append(column)
        else:
            clusters.append([column])
    # Keep clusters that recur; a one-off is a number inside a description.
    # A column recurs; a one-off is a number inside a description.
    threshold = max(2, dated_count // 12)
    strong = [max(c) for c in clusters if sum(ends[col] for col in c) >= threshold]
    if not strong:
        return [max(ends)]
    # Amount columns sit to the right. Anything far left of the rightmost one is
    # description content — a reference number or an exchange rate — however
    # regularly it recurs.
    rightmost = max(strong)
    return [column for column in strong if column >= rightmost - 80]


def _header_line(pages: list[Page], dated: list[Line]) -> str:
    """The last amount-free line above the first dated line, on its page."""
    first = dated[0]
    page = next(p for p in pages if p.number == first.page)
    for line in reversed(page.lines[: first.number]):
        if line.stripped and not line.amounts and len(line.stripped.split()) >= 2:
            return line.text
    return ""


def _header_anchor(header: str) -> str:
    """A loose pattern for a column header, from its first few words."""
    from .text import loose

    words = [w for w in header.split() if len(w) > 1][:4]
    return r"^\s*" + r"\s+".join(loose(word) for word in words) if words else r"^"


def _infer_codes(dated: list[Line], shape: str) -> list[TypeCode]:
    """Short tokens that recur immediately after the date are a code column."""
    pattern = re.compile(rf"^\s*{shape}\s+(\S+)")
    tokens = Counter()
    for line in dated:
        match = pattern.match(line.text)
        if match and len(match.group(1)) <= 5:
            tokens[match.group(1)] += 1
    # A code repeats; a merchant's first word usually does not.
    common = [t for t, n in tokens.items() if n >= 3 and not t.replace(".", "").isdigit()]
    if len(common) > 12 or not common:
        return []
    return [TypeCode(token, Direction.AMBIGUOUS, "inferred") for token in sorted(common)]


def _infer_stops(pages: list[Page], dated: list[Line]) -> list[str]:
    """Prose after the last transaction marks the end of the table."""
    last = dated[-1]
    page = next(p for p in pages if p.number == last.page)
    for line in page.lines[last.number + 1 :]:
        words = line.stripped.split()
        if len(words) >= 6 and not line.amounts and any(w.islower() for w in words):
            return [re.escape(" ".join(words[:5]))]
    return [r"Financial Services Compensation Scheme", r"IN CASE OF ERRORS"]


def _infer_summary(lines: list[Line]) -> dict[str, re.Pattern]:
    """Find the summary box by looking for known label wordings beside a total."""
    found: dict[str, re.Pattern] = {}
    for line in lines:
        match = AMOUNT_LABEL.search(line.text)
        if not match:
            continue
        label = " ".join(match.group(1).split()).lower().strip(" :-")
        for field, wordings in SUMMARY_WORDINGS.items():
            if field in found:
                continue
            for wording in wordings:
                if label.endswith(wording):
                    found[field] = re.compile(
                        re.escape(wording).replace(r"\ ", r"\s+")
                        + r"\s*[:+-]?\s*[$£€]?\s*([\d, ]+\.\s?\d{2})",
                        re.I,
                    )
                    break
    return found


def _infer_currency(lines: list[Line]) -> str:
    """Whichever currency symbol the document actually uses."""
    text = "\n".join(line.text for line in lines)
    counts = {"GBP": text.count("£"), "USD": text.count("$"), "EUR": text.count("€")}
    best = max(counts, key=counts.get)
    return best if counts[best] else "USD"
