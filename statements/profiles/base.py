"""The shape every bank profile fills in."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable


class Direction(str, Enum):
    OUT = "out"  # money left the account
    IN = "in"  # money arrived
    AMBIGUOUS = "ambiguous"  # code alone can't say; balance validation decides


@dataclass(frozen=True)
class TypeCode:
    """One of the bank's transaction codes and what it implies about direction."""

    code: str
    direction: Direction
    label: str = ""


@dataclass
class Profile:
    """A statement layout.

    Region detection (`table_start`/`table_continues`/`table_stop`) decides which
    lines are transactions at all; everything before the start and after the stop
    is address blocks, summary boxes and boilerplate.
    """

    name: str
    bank: str
    description: str
    currency: str

    # --- where the transaction table lives on a page -----------------------
    # Matched loosely on purpose: spacing and kerning shift between pages and
    # between PDF generator versions.
    table_start: list[re.Pattern]
    table_stop: list[re.Pattern]
    # 1 starts the table on the line after the anchor (a column header); 0
    # includes the anchor itself, for layouts whose anchor is a section
    # divider that also sets direction.
    table_start_offset: int = 1
    # Continuation pages carry no header of their own.
    table_continues: list[re.Pattern] = field(default_factory=list)
    # If a continuation page has no marker either, assume it opens mid-table.
    continues_by_default: bool = False

    # --- the summary box, read independently as ground truth ---------------
    summary_patterns: dict[str, re.Pattern] = field(default_factory=dict)
    period_pattern: re.Pattern | None = None
    account_pattern: re.Pattern | None = None
    # Whose account this is, taken from the statement itself.
    owner_pattern: re.Pattern | None = None
    # A statement can cover several cardholders in sequence. A match here
    # switches the owner (and account id) for everything that follows.
    owner_section_pattern: re.Pattern | None = None
    sheet_pattern: re.Pattern | None = None
    page_pattern: re.Pattern | None = None

    # --- reading a transaction line ----------------------------------------
    # May carry named groups `txn` and `posting` where the bank prints both a
    # transaction date and a posting date; otherwise group 1 is the date.
    date_pattern: re.Pattern | None = None
    parse_date: Callable[[str], date] | None = None
    # Card statements have no code column: a leading date is what marks a new
    # transaction, and everything else on the line is description.
    date_starts_transaction: bool = False
    # "first_token": the bank prints a code column (HSBC UK style).
    # "description_prefix": no code column; classify on the leading words.
    code_source: str = "first_token"
    codes: tuple[TypeCode, ...] = ()
    # "sigil": the running balance is the currency-symbol-marked amount.
    # "column": the running balance is whatever sits right of balance_min_col.
    # "none": no running balance is printed, so only the statement-level check
    # can run.
    balance_marker: str = "column"
    # "columns": paid-out and paid-in are separate columns.
    # "suffix": one column, with CR marking the entries that go the other way.
    amount_sign_mode: str = "columns"
    # Code applied when no vocabulary entry matches — card statements label
    # every unrecognised line a purchase rather than dropping it.
    default_code: str = ""
    default_direction: Direction = Direction.OUT

    # --- column geometry (character columns in layout text) -----------------
    # Amounts ending left of this are description content — foreign-currency
    # amounts, exchange rates, reference numbers — never the transaction amount.
    # This is a floor; the effective bound is calibrated per page, because the
    # whole amount block shifts between a statement's first and later pages.
    description_max_col: int = 46
    # How far left of the balance column the amount columns can reach. The
    # transaction amount is always within this band; anything further left is
    # description content, whatever the page's absolute geometry.
    amount_band_width: int = 55
    # Which side of the split money-in sits on. HSBC US prints deposits left
    # of withdrawals; HSBC UK prints paid-out left of paid-in. Getting this
    # backwards inverts every ambiguous transaction on the page.
    paid_in_side: str = "left"
    # Fallback in/out split, used only until per-page calibration kicks in.
    default_in_out_split: int = 80
    balance_min_col: int = 105

    # "asset": a deposit account, where closing = opening + in - out.
    # "liability": a card, where money out *increases* what is owed, so
    # closing = opening + out - in. Getting this backwards inverts the check.
    balance_sign: str = "asset"

    # Some statements group transactions under section headings and let the
    # heading decide direction ("Deposits/Other Credits", then "Other Debits"),
    # rather than using columns or codes.
    section_patterns: list[tuple[re.Pattern, Direction]] = field(default_factory=list)

    # --- lines that state a balance rather than move money ------------------
    checkpoint_patterns: list[re.Pattern] = field(default_factory=list)
    # Lines to drop outright even inside the table region.
    noise_patterns: list[re.Pattern] = field(default_factory=list)

    def code_for(self, token: str) -> TypeCode | None:
        for code in self.codes:
            if code.code == token:
                return code
        return None

    @property
    def is_liability(self) -> bool:
        return self.balance_sign == "liability"

    def match_code(self, text: str) -> TypeCode | None:
        """Find this line's type code, per the profile's `code_source`."""
        if self.code_source == "first_token":
            token = text.split(maxsplit=1)
            return self.code_for(token[0]) if token else None
        # Collapse runs of whitespace first: OCR pads between words, and PDF
        # kerning inserts spaces, so "Wire     Deposit" must still match.
        upper = " ".join(text.upper().split())
        # Longest prefix wins, so "INTEREST PAID" beats a bare "INTEREST".
        for code in sorted(self.codes, key=lambda c: -len(c.code)):
            if upper.startswith(" ".join(code.code.upper().split())):
                return code
        return None

    def match_section(self, text: str) -> Direction | None:
        """The direction a section heading imposes on the lines that follow."""
        for pattern, direction in self.section_patterns:
            if pattern.search(text):
                return direction
        return None

    def is_checkpoint(self, text: str) -> bool:
        return any(p.search(text) for p in self.checkpoint_patterns)

    def is_noise(self, text: str) -> bool:
        return any(p.search(text) for p in self.noise_patterns)
