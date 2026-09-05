"""The parsing engine: layout pages in, transactions and balance checkpoints out.

The engine is profile-driven; nothing here knows about a particular bank.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .layout import Amount, Line, Page, load_pages, split_pages
from .profiles import Direction, Profile, TypeCode

# A foreign-currency amount left in the description, e.g. "EUR 45.00".
FOREIGN_RE = re.compile(r"\b([A-Z]{3})\s*([\d,]+\.\d{2})\b")
# HSBC US descriptions embed the card transaction date: "PURCHASE ON 0107 AT ..."
CARD_DATE_RE = re.compile(r"\bON\s+(\d{4}|\d{8})\s+AT\b")


@dataclass
class Transaction:
    source_file: str
    page_number: int
    line_number: int
    txn_date: date | None
    type_code: str
    description: str
    amount: int  # magnitude in minor units; direction is held separately
    direction: Direction
    direction_certain: bool
    printed_balance: int | None = None
    amount_end_col: int = 0
    foreign_amount: int | None = None
    foreign_currency: str = ""
    card_date: str = ""
    direction_confidence: str = "certain"
    reconciliation_note: str = ""

    @property
    def signed(self) -> int:
        """Positive = money out, matching the target workbook's convention."""
        return self.amount if self.direction is Direction.OUT else -self.amount


@dataclass
class Checkpoint:
    """A balance the bank printed, used as ground truth by reconciliation."""

    page_number: int
    line_number: int
    label: str
    balance: int


@dataclass
class StatementDoc:
    source_file: str
    profile: str
    currency: str
    account: str = ""
    period_start: date | None = None
    period_end: date | None = None
    sheet_number: str = ""
    page_count: int = 0
    opening_balance: int | None = None
    closing_balance: int | None = None
    printed_paid_in: int | None = None
    printed_paid_out: int | None = None
    transactions: list[Transaction] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Region detection
# --------------------------------------------------------------------------- #

def table_region(page: Page, profile: Profile) -> tuple[int, int] | None:
    """The (start, stop) line range holding transactions, or None if this page
    has no transaction table at all."""
    start = None
    for pattern in profile.table_start:
        found = page.find(pattern)
        if found is not None:
            start = found + 1
            break
    if start is None:
        for pattern in profile.table_continues:
            found = page.find(pattern)
            if found is not None:
                start = found + 1
                break
    if start is None:
        return None

    stop = len(page.lines)
    for pattern in profile.table_stop:
        for line in page.lines[start:]:
            if pattern.search(line.text):
                stop = min(stop, line.number)
                break
    return (start, stop) if stop > start else None


# --------------------------------------------------------------------------- #
# Column calibration
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Geometry:
    """Where this page's amount columns actually sit."""

    amount_min: int  # amounts ending left of this are description content
    in_out_split: int  # boundary between the paid-in and paid-out columns
    balance_min: int
    paid_in_left: bool  # is the money-in column the left of the two?


def calibrate_page(lines: list[Line], profile: Profile) -> Geometry:
    """Work out this page's amount geometry from its own content.

    Column positions shift between a statement's first page, its middle pages
    and its last page, so every page is measured independently. Lines whose
    direction the type code already settles act as the anchors.
    """
    balance_cols: list[int] = []
    out_cols: list[int] = []
    in_cols: list[int] = []

    # First pass: find the balance column, which anchors everything else.
    for line in lines:
        amounts = [a for a in line.amounts if a.end_col >= profile.description_max_col]
        balance, _ = _split_balance(amounts, profile, profile.balance_min_col)
        if balance is not None:
            balance_cols.append(balance.end_col)

    balance_min = min(balance_cols) - 1 if balance_cols else profile.balance_min_col
    amount_min = max(profile.description_max_col, balance_min - profile.amount_band_width)

    # Second pass: measure the in/out columns from lines whose type code already
    # settles their direction.
    for line in lines:
        amounts = [a for a in line.amounts if a.end_col >= amount_min]
        if not amounts:
            continue
        balance, txn = _split_balance(amounts, profile, balance_min)
        if txn is None:
            continue
        code = profile.match_code(_code_text(line, profile))
        if code is None:
            continue
        if code.direction is Direction.OUT:
            out_cols.append(txn.end_col)
        elif code.direction is Direction.IN:
            in_cols.append(txn.end_col)

    in_left = profile.paid_in_side == "left"
    if out_cols and in_cols:
        # Split midway between the two clusters, whichever order they come in.
        split = (max(in_cols) + min(out_cols)) // 2 if in_left else (
            (max(out_cols) + min(in_cols)) // 2
        )
    elif out_cols:
        split = min(out_cols) - 1 if in_left else max(out_cols)
    elif in_cols:
        split = max(in_cols) if in_left else min(in_cols) - 1
    else:
        split = profile.default_in_out_split
    return Geometry(
        amount_min=amount_min,
        in_out_split=split,
        balance_min=balance_min,
        paid_in_left=in_left,
    )


def _split_balance(
    amounts: list[Amount], profile: Profile, balance_min: int
) -> tuple[Amount | None, Amount | None]:
    """Separate the running balance from the transaction amount on one line."""
    if profile.balance_marker == "sigil":
        marked = [a for a in amounts if a.has_sigil]
        balance = marked[-1] if marked else None
    else:
        right = [a for a in amounts if a.end_col >= balance_min]
        balance = right[-1] if right else None

    rest = [a for a in amounts if a is not balance]
    # Where a line carries two amounts, the leftmost is the transaction and the
    # rightmost is the balance printed beside it.
    return balance, rest[0] if rest else None


def _code_text(line: Line, profile: Profile) -> str:
    """The part of a line the type code is read from, with any leading date gone."""
    text = line.text
    if profile.date_pattern is not None:
        match = profile.date_pattern.match(text)
        if match:
            text = text[match.end() :]
    return text.strip()


# --------------------------------------------------------------------------- #
# Line parsing
# --------------------------------------------------------------------------- #

def parse_page(
    page: Page,
    profile: Profile,
    source_file: str,
    carried_date: date | None,
) -> tuple[list[Transaction], list[Checkpoint], date | None, list[str]]:
    """Parse one page's transaction table."""
    region = table_region(page, profile)
    if region is None:
        return [], [], carried_date, []

    start, stop = region
    lines = [ln for ln in page.lines[start:stop] if ln.stripped and not profile.is_noise(ln.text)]
    if not lines:
        return [], [], carried_date, []

    geometry = calibrate_page(lines, profile)
    transactions: list[Transaction] = []
    checkpoints: list[Checkpoint] = []
    warnings: list[str] = []
    open_txn: Transaction | None = None

    for line in lines:
        current_date, remainder = _take_date(line, profile)
        if current_date is not None:
            carried_date = current_date

        amounts = [a for a in line.amounts if a.end_col >= geometry.amount_min]
        balance, txn_amount = _split_balance(amounts, profile, geometry.balance_min)

        if profile.is_checkpoint(remainder):
            if balance is not None:
                checkpoints.append(
                    Checkpoint(page.number, line.number, remainder.strip()[:40], balance.value)
                )
            open_txn = None
            continue

        code = profile.match_code(remainder)
        if code is not None:
            # A new transaction starts here, whether or not its amount is on
            # this line — wires and foreign-currency purchases often push the
            # amount two to four lines further down.
            open_txn = _start_transaction(
                line, remainder, amounts, code, carried_date, source_file, profile, geometry
            )
            transactions.append(open_txn)
            if open_txn.amount is None:
                continue
        elif open_txn is not None:
            # Continuation: extra description, or the amount arriving late.
            _extend_transaction(open_txn, remainder, txn_amount, balance, geometry)
        elif remainder:
            warnings.append(
                f"p.{page.number} line {line.number}: no type code and no open "
                f"transaction — skipped: {remainder[:60]!r}"
            )

    incomplete = [t for t in transactions if t.amount is None]
    for txn in incomplete:
        warnings.append(
            f"p.{txn.page_number} line {txn.line_number}: transaction has no amount "
            f"— skipped: {txn.description[:60]!r}"
        )
    transactions = [t for t in transactions if t.amount is not None]
    for txn in transactions:
        _finalise(txn)
    return transactions, checkpoints, carried_date, warnings


def _take_date(line: Line, profile: Profile) -> tuple[date | None, str]:
    """Pull a leading date off a line, returning it and the rest of the line."""
    if profile.date_pattern is None:
        return None, line.stripped
    match = profile.date_pattern.match(line.text)
    if not match:
        return None, line.stripped
    try:
        parsed = profile.parse_date(match.group(1)) if profile.parse_date else None
    except ValueError:
        parsed = None
    return parsed, line.text[match.end() :].strip()


def _start_transaction(
    line: Line,
    remainder: str,
    amounts: list[Amount],
    code: TypeCode,
    txn_date: date | None,
    source_file: str,
    profile: Profile,
    geometry: Geometry,
) -> Transaction:
    balance, txn_amount = _split_balance(amounts, profile, geometry.balance_min)
    description = line.text_before(txn_amount.start_col if txn_amount else len(line.text))
    if profile.date_pattern is not None:
        description = profile.date_pattern.sub("", description, count=1).strip()

    certain = code.direction is not Direction.AMBIGUOUS
    return Transaction(
        source_file=source_file,
        page_number=line.page,
        line_number=line.number,
        txn_date=txn_date,
        type_code=code.code,
        description=description or remainder,
        amount=txn_amount.value if txn_amount else None,
        # A code that can post either way gets a provisional direction from the
        # column its amount sits in; reconciliation confirms or flips it.
        direction=code.direction if certain else _direction_from_column(txn_amount, geometry),
        direction_certain=certain,
        printed_balance=balance.value if balance else None,
        amount_end_col=txn_amount.end_col if txn_amount else 0,
    )


def _direction_from_column(amount: Amount | None, geometry: Geometry) -> Direction:
    if amount is None:
        return Direction.OUT
    left_of_split = amount.end_col <= geometry.in_out_split
    money_in = left_of_split if geometry.paid_in_left else not left_of_split
    return Direction.IN if money_in else Direction.OUT


def _extend_transaction(
    txn: Transaction, text: str, txn_amount: Amount | None, balance: Amount | None,
    geometry: Geometry,
) -> None:
    """Fold a continuation line into the transaction it belongs to."""
    if txn_amount is not None and txn.amount is None:
        txn.amount = txn_amount.value
        txn.amount_end_col = txn_amount.end_col
        if not txn.direction_certain:
            txn.direction = _direction_from_column(txn_amount, geometry)
    if balance is not None and txn.printed_balance is None:
        txn.printed_balance = balance.value
    # Keep description text, but not the amount columns themselves.
    tail = text
    if txn_amount is not None:
        tail = text.split(txn_amount.text)[0]
    if balance is not None:
        tail = tail.split(balance.text)[0]
    tail = tail.strip()
    if tail:
        txn.description = f"{txn.description} {tail}".strip()


def _finalise(txn: Transaction) -> None:
    """Pull structured detail out of the assembled description."""
    foreign = FOREIGN_RE.search(txn.description)
    if foreign:
        currency, value = foreign.groups()
        txn.foreign_currency = currency
        txn.foreign_amount = int(value.replace(",", "").replace(".", ""))
    card_date = CARD_DATE_RE.search(txn.description)
    if card_date:
        txn.card_date = card_date.group(1)
    txn.description = " ".join(txn.description.split())


# --------------------------------------------------------------------------- #
# Whole document
# --------------------------------------------------------------------------- #

def parse_statement(pdf: Path | str, profile: Profile, text: str | None = None) -> StatementDoc:
    """Parse one statement PDF (or pre-extracted layout text, for tests)."""
    source = Path(pdf).name
    pages = split_pages(text) if text is not None else load_pages(pdf)
    doc = StatementDoc(
        source_file=source, profile=profile.name, currency=profile.currency, page_count=len(pages)
    )
    whole = "\n".join(page.text for page in pages)
    _read_summary(doc, whole, profile)

    carried: date | None = None
    for page in pages:
        txns, checkpoints, carried, warnings = parse_page(page, profile, source, carried)
        doc.transactions.extend(txns)
        doc.checkpoints.extend(checkpoints)
        doc.warnings.extend(warnings)

    if not doc.transactions:
        doc.warnings.append(
            "No transactions parsed. Check the table-start pattern against this "
            f"file: python -m statements.cli dump {source}"
        )
    return doc


def _read_summary(doc: StatementDoc, text: str, profile: Profile) -> None:
    """Read the account summary box — the ground truth we validate against."""
    from .money import parse_money

    for field_name, pattern in profile.summary_patterns.items():
        match = pattern.search(text)
        if match:
            setattr(doc, field_name, parse_money(match.group(1)))
        else:
            doc.warnings.append(f"Could not read {field_name.replace('_', ' ')} from the summary.")

    if profile.period_pattern and (match := profile.period_pattern.search(text)):
        try:
            doc.period_start = profile.parse_date(match.group(1))
            doc.period_end = profile.parse_date(match.group(2))
        except ValueError:
            doc.warnings.append(f"Could not parse statement period: {match.group(0)!r}")
    if profile.account_pattern and (match := profile.account_pattern.search(text)):
        doc.account = match.group(1).strip()
    if profile.sheet_pattern and (match := profile.sheet_pattern.search(text)):
        doc.sheet_number = match.group(1).strip()
