"""OCR for scanned statements, for PDFs that carry no text layer.

Tesseract's word boxes are reflowed into fixed-width layout text so the rest of
the pipeline — which reads meaning from character columns — works unchanged.

A caution that belongs with any OCR of financial data: the reconciliation check
catches a misread *amount*, because the statement stops balancing. It does not
catch a misread date or merchant name. Rows extracted this way are stamped
`ocr` in `reconciliation_note` so they can be spot-checked.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from pathlib import Path

from .layout import FORM_FEED

# Rendering resolution. 300dpi is the usual floor for reliable digit recognition
# on statement print.
DEFAULT_DPI = 300
# Width of the reconstructed layout text, in characters.
LAYOUT_WIDTH = 160


class TesseractMissing(RuntimeError):
    """tesseract is not on PATH."""


def has_text_layer(pdf: Path | str) -> bool:
    """True if the PDF carries real text — i.e. does not need OCR."""
    from .layout import pdf_to_layout_text

    try:
        return bool(pdf_to_layout_text(pdf).strip())
    except Exception:
        return False


def _require(binary: str) -> None:
    if shutil.which(binary) is None:
        raise TesseractMissing(
            f"{binary} not found; needed to read scanned statements.\n"
            "  Debian/Ubuntu:  sudo apt-get install tesseract-ocr poppler-utils\n"
            "  macOS:          brew install tesseract poppler"
        )


def ocr_pdf(pdf: Path | str, dpi: int = DEFAULT_DPI, language: str = "eng") -> str:
    """OCR a scanned PDF into layout-preserved text, page-separated by form feed."""
    _require("tesseract")
    _require("pdftoppm")

    import tempfile

    pages: list[str] = []
    with tempfile.TemporaryDirectory() as workdir:
        prefix = Path(workdir) / "page"
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-gray", "-png", str(pdf), str(prefix)],
            capture_output=True,
            check=True,
        )
        for image in sorted(Path(workdir).glob("page-*.png")):
            pages.append(_ocr_image(image, language))
    return FORM_FEED.join(pages)


def _ocr_image(image: Path, language: str) -> str:
    """One page image -> layout text, via tesseract's word-box output."""
    result = subprocess.run(
        ["tesseract", str(image), "stdout", "-l", language, "--psm", "6", "tsv"],
        capture_output=True,
        check=True,
    )
    return words_to_layout(result.stdout.decode("utf-8", errors="replace"))


def words_to_layout(tsv: str, width: int = LAYOUT_WIDTH) -> str:
    """Rebuild fixed-width text from tesseract TSV word boxes.

    Words are grouped into lines by tesseract's own line numbering, then placed
    at the character column their pixel position implies — which is what makes
    the column-position logic in the parser applicable to a scan.
    """
    rows = list(csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE))
    words = [
        r
        for r in rows
        if r.get("text", "").strip() and _to_int(r.get("conf", "-1")) >= 0
    ]
    if not words:
        return ""

    page_width = max(_to_int(w["left"]) + _to_int(w["width"]) for w in words) or 1
    scale = width / page_width

    lines: dict[tuple[int, int, int], list[dict]] = {}
    for word in words:
        key = (_to_int(word["block_num"]), _to_int(word["par_num"]), _to_int(word["line_num"]))
        lines.setdefault(key, []).append(word)

    rendered = []
    for key in sorted(lines, key=lambda k: min(_to_int(w["top"]) for w in lines[k])):
        rendered.append(_render_line(lines[key], scale, width))
    return "\n".join(rendered)


def _render_line(words: list[dict], scale: float, width: int) -> str:
    line = ""
    for word in sorted(words, key=lambda w: _to_int(w["left"])):
        column = int(_to_int(word["left"]) * scale)
        text = repair_numeric_token(word["text"].strip())
        if column < len(line):
            # Overlap after scaling: keep a single separating space rather than
            # letting words run together into one token.
            column = len(line) + 1
        line = line.ljust(column) + text
    return line[:width] if width else line


# Letters tesseract routinely returns in place of digits on statement print.
_DIGIT_LOOKALIKES = str.maketrans({
    "O": "0", "o": "0", "D": "0", "Q": "0",
    "l": "1", "I": "1", "|": "1",
    "S": "5", "s": "5", "§": "5",
    "B": "8", "Z": "2", "G": "6",
})
# A token worth repairing: made only of digits, separators and the letters
# above. Anything containing another letter is a word and is left alone.
_NUMERIC_SHAPE = re.compile(r"^[\d.,/\-+$£€()OoDQlI|SsBZG§]+$")


def repair_numeric_token(token: str) -> str:
    """Fix digit/letter confusions inside a token that is already mostly numeric.

    This cannot fix a digit misread as another digit — `12/14/2023` coming back
    as `12/14/2025` is indistinguishable from correct input, which is why OCR
    output still needs the reconciliation check and a sanity check on dates.
    """
    stripped = token.strip()
    if not stripped or not _NUMERIC_SHAPE.match(stripped):
        return token
    digits = sum(c.isdigit() for c in stripped)
    letters = sum(c.isalpha() for c in stripped)
    # Require a numeric majority, so "SO" or "OO" is never turned into digits.
    if digits == 0 or letters > digits:
        return token
    return stripped.translate(_DIGIT_LOOKALIKES)


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return -1
