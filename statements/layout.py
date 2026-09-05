"""Layout-preserved text extraction. Column alignment is load-bearing here, so
this is `pdftotext -layout` (poppler), not a flat-text extractor."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .money import AMOUNT_RE, _from_match

FORM_FEED = "\x0c"


class PopplerMissing(RuntimeError):
    """pdftotext is not on PATH."""


@dataclass(frozen=True)
class Amount:
    """A currency amount together with where it sat on the line.

    `end_col` is what distinguishes a transaction amount from a running balance
    or from a number buried in the description, so it travels with the value.
    """

    value: int
    start_col: int
    end_col: int
    has_sigil: bool
    text: str
    # "CR"/"DR" where the bank pre-signs a single amount column. Its meaning is
    # profile-specific, so it is carried rather than interpreted here.
    suffix: str = ""


@dataclass
class Line:
    """One line of layout text, with its amounts already located."""

    page: int
    number: int  # 0-based index within the page
    text: str

    def __post_init__(self) -> None:
        self.amounts = _find_amounts(self.text)

    @property
    def stripped(self) -> str:
        return self.text.strip()

    @property
    def indent(self) -> int:
        return len(self.text) - len(self.text.lstrip())

    def text_before(self, col: int) -> str:
        """The line's text left of `col` — i.e. the description, minus amounts."""
        return self.text[:col].strip()


@dataclass
class Page:
    number: int  # 1-based
    lines: list[Line]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def find(self, pattern: re.Pattern) -> int | None:
        """Index of the first line matching `pattern`, or None."""
        for line in self.lines:
            if pattern.search(line.text):
                return line.number
        return None


def _find_amounts(text: str) -> list[Amount]:
    amounts = []
    for match in AMOUNT_RE.finditer(text):
        # Reject a decimal glued to surrounding word characters (reference
        # numbers, "5966.00ABC"), which is never a column amount.
        before = text[match.start() - 1] if match.start() else " "
        after = text[match.end()] if match.end() < len(text) else " "
        if before.isalnum() or after.isalnum():
            continue
        suffix = match.group("trailing") or ""
        amounts.append(
            Amount(
                value=_from_match(match),
                start_col=match.start(),
                end_col=match.end(),
                has_sigil=bool(match.group("sigil")),
                text=match.group(0),
                suffix=suffix if suffix in {"CR", "DR"} else "",
            )
        )
    return amounts


def pdf_to_layout_text(pdf: Path | str) -> str:
    """Run `pdftotext -layout`. Raises PopplerMissing if poppler isn't installed."""
    if shutil.which("pdftotext") is None:
        raise PopplerMissing(
            "pdftotext not found. Install poppler-utils:\n"
            "  Debian/Ubuntu:  sudo apt-get install poppler-utils\n"
            "  macOS:          brew install poppler"
        )
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def split_pages(text: str) -> list[Page]:
    """Split layout text on form feeds, dropping trailing blank pages."""
    pages = []
    for index, chunk in enumerate(text.split(FORM_FEED), start=1):
        lines = [Line(page=index, number=n, text=t) for n, t in enumerate(chunk.split("\n"))]
        pages.append(Page(number=index, lines=lines))
    while pages and not pages[-1].text.strip():
        pages.pop()
    return pages


def load_pages(pdf: Path | str) -> list[Page]:
    return split_pages(pdf_to_layout_text(pdf))
