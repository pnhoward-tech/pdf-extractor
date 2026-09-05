"""Table extraction from text-based (non-scanned) PDFs, built on pdfplumber."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import BinaryIO, Iterable

import pdfplumber

# pdfplumber settings: ruled tables first (accurate when the PDF draws borders),
# then a whitespace-alignment pass for borderless tables.
_LINE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
}
_TEXT_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "intersection_tolerance": 5,
    "text_tolerance": 2,
}


@dataclass
class RawTable:
    """One table found in one PDF, already split into a header row and body rows."""

    page: int
    index: int
    header: list[str]
    rows: list[list[str]] = field(default_factory=list)
    strategy: str = "lines"

    @property
    def width(self) -> int:
        return len(self.header)


@dataclass
class Document:
    """Everything we pulled out of a single PDF."""

    filename: str
    text: str
    tables: list[RawTable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def clean_cell(value: object) -> str:
    """Normalise one extracted cell: collapse wrapped lines and runs of spaces."""
    if value is None:
        return ""
    text = str(value).replace(" ", " ")
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _clean_rows(rows: Iterable[Iterable[object]]) -> list[list[str]]:
    cleaned = []
    for row in rows:
        cells = [clean_cell(c) for c in row]
        if any(cells):  # drop rows that are entirely blank
            cleaned.append(cells)
    return cleaned


def _pad(row: list[str], width: int) -> list[str]:
    """Force a row to `width` columns; over-long rows keep their tail in the last cell."""
    if len(row) == width:
        return row
    if len(row) < width:
        return row + [""] * (width - len(row))
    head, tail = row[: width - 1], row[width - 1 :]
    return head + [" ".join(p for p in tail if p)]


def _looks_like_header(row: list[str]) -> bool:
    """Headers are mostly short, mostly non-numeric labels."""
    filled = [c for c in row if c]
    if len(filled) < 2:
        return False
    numericish = sum(1 for c in filled if re.fullmatch(r"[-+$€£(]?[\d.,%)\s]+", c))
    return numericish <= len(filled) / 2


def _extract_page_tables(page: pdfplumber.page.Page) -> list[tuple[list[list[str]], str]]:
    """Return (rows, strategy) per table, preferring ruled detection over text alignment."""
    for strategy, settings in (("lines", _LINE_SETTINGS), ("text", _TEXT_SETTINGS)):
        try:
            found = page.extract_tables(settings)
        except Exception:  # pdfplumber can throw on malformed page content
            continue
        usable = [(_clean_rows(t), strategy) for t in found or []]
        usable = [(rows, s) for rows, s in usable if len(rows) >= 2]
        if usable:
            return usable
    return []


def extract_document(source: BinaryIO | bytes, filename: str = "document.pdf") -> Document:
    """Read one PDF and return its page text plus every table we can find.

    Tables that continue onto the next page (same column count, no header row of
    their own) are stitched back onto the table they continue.
    """
    stream = io.BytesIO(source) if isinstance(source, bytes) else source
    doc = Document(filename=filename, text="")
    text_parts: list[str] = []

    with pdfplumber.open(stream) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text_parts.append(page.extract_text() or "")
            for table_no, (rows, strategy) in enumerate(_extract_page_tables(page)):
                header, body = rows[0], rows[1:]
                previous = doc.tables[-1] if doc.tables else None
                is_continuation = (
                    previous is not None
                    and table_no == 0
                    and previous.page == page_no - 1
                    and previous.width == len(header)
                    and not _looks_like_header(header)
                )
                if is_continuation:
                    previous.rows.extend(_pad(r, previous.width) for r in rows)
                    continue

                width = len(header)
                doc.tables.append(
                    RawTable(
                        page=page_no,
                        index=table_no,
                        header=_pad([c or f"column_{i + 1}" for i, c in enumerate(header)], width),
                        rows=[_pad(r, width) for r in body],
                        strategy=strategy,
                    )
                )

    doc.text = "\n".join(text_parts)
    if not doc.tables:
        doc.warnings.append(
            "No tables detected. If this PDF is a scan, it needs OCR first — this tool "
            "only reads PDFs that contain real text."
        )
    elif not doc.text.strip():
        doc.warnings.append("No text layer found; extracted tables may be empty.")
    return doc
