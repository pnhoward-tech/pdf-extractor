"""Tolerating what PDF text extraction does to words.

HSBC's statement PDFs space characters unevenly, so `pdftotext` returns
"Ope ning Balance", "Paym e nts In", "S he e t Num be r" — and inside numbers,
"£35,349 .65". The breaks are not stable between documents or even between
pages, so patterns are built to tolerate them rather than enumerate them.
"""

from __future__ import annotations

import re

# Kerning inserts one or two spaces, never a line's worth, so the tolerance is
# bounded. An unbounded \s* would happily match across a column gap.
GAP = "[ ]{0,2}"


def loose(literal: str) -> str:
    """A regex matching `literal` even if spaces are sprinkled through it.

    >>> re.search(loose("Opening Balance"), "Ope ning Balance").group(0)
    'Ope ning Balance'
    """
    parts = []
    for word in literal.split():
        parts.append(GAP.join(re.escape(char) for char in word))
    return r"\s+".join(parts)


def loose_pattern(literal: str, *, flags: int = re.IGNORECASE) -> re.Pattern:
    return re.compile(loose(literal), flags)


def dekern(text: str) -> str:
    """Collapse a kerned string for comparison: strip every space.

    Only safe on short labels being compared to each other, never on a
    description — it would join genuinely separate words.
    """
    return re.sub(r"\s+", "", text).lower()
