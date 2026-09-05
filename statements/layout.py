"""Layout-preserved text extraction.

Column alignment is load-bearing throughout the parser, so this is never a
flat-text extractor. Two backends produce it:

* `pdftotext -layout` (poppler) — the reference, and what the profiles' column
  numbers were measured against.
* pdfplumber — pure Python, available with `backend="pdfplumber"` for
  diagnostics on a machine without poppler.

**poppler is required, not preferred.** The pdfplumber grid was measured
against the same statements and comes out close but not equal: it collapses the
kerned gaps inside words, which moves the columns the profiles were calibrated
on. Five of seven real statements stopped reconciling on it. Since a profile's
column numbers can only be right for one grid, the fallback is not used
automatically — a missing poppler is reported so it can be installed, rather
than quietly producing statements that fail their own check.
"""

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
        # The pattern absorbs leading spaces so that kerned amounts still match,
        # so measure from the first real character, not from the match start.
        raw = match.group(0)
        start = match.start() + (len(raw) - len(raw.lstrip(" ")))
        # Reject a decimal glued to surrounding word characters (reference
        # numbers, "5966.00ABC"), which is never a column amount.
        before = text[start - 1] if start else " "
        after = text[match.end()] if match.end() < len(text) else " "
        if before.isalnum() or after.isalnum():
            continue
        suffix = match.group("trailing") or ""
        amounts.append(
            Amount(
                value=_from_match(match),
                start_col=start,
                end_col=match.end(),
                has_sigil=bool(match.group("sigil")),
                text=raw.strip(),
                suffix=suffix if suffix in {"CR", "DR"} else "",
            )
        )
    return amounts


# Points per character. Chosen so pdfplumber's grid lands close to poppler's,
# which is what the profiles' column numbers were measured against.
PDFPLUMBER_X_DENSITY = 4.75


def have_poppler() -> bool:
    return shutil.which("pdftotext") is not None


def pdf_to_layout_text(pdf: Path | str, backend: str = "auto") -> str:
    """Layout-preserved text for a PDF.

    `backend` is "auto" (poppler if present, else pdfplumber), "poppler" or
    "pdfplumber".
    """
    if backend != "pdfplumber":
        if not have_poppler():
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
    return pdfplumber_layout_text(pdf)


def pdfplumber_layout_text(pdf: Path | str) -> str:
    """Layout text without any external binary."""
    import pdfplumber

    pages = []
    with pdfplumber.open(str(pdf)) as document:
        for page in document.pages:
            pages.append(
                page.extract_text(layout=True, x_density=PDFPLUMBER_X_DENSITY) or ""
            )
    return FORM_FEED.join(pages)


def split_pages(text: str) -> list[Page]:
    """Split layout text on form feeds, dropping trailing blank pages."""
    pages = []
    for index, chunk in enumerate(text.split(FORM_FEED), start=1):
        lines = [Line(page=index, number=n, text=t) for n, t in enumerate(chunk.split("\n"))]
        pages.append(Page(number=index, lines=lines))
    while pages and not pages[-1].text.strip():
        pages.pop()
    return pages


def load_pages(pdf: Path | str, backend: str = "auto") -> list[Page]:
    return split_pages(pdf_to_layout_text(pdf, backend=backend))
