"""Money as integer minor units (cents/pence). Never floats — this all has to
reconcile to the penny."""

from __future__ import annotations

import re

# A currency amount, optionally $/£/€-prefixed, optionally parenthesised or
# minus-signed, always with two decimal places.
AMOUNT_RE = re.compile(
    r"""
    (?P<paren>\()?
    (?P<sign>-)?
    (?P<sigil>[$£€])?
    (?P<whole>\d{1,3}(?:,\d{3})+|\d+)
    \.
    (?P<cents>\d{2})
    (?P<close>\))?
    (?P<trailing>-|CR|DR)?
    """,
    re.VERBOSE,
)


def parse_money(text: str) -> int:
    """'$1,234.56' -> 123456. '(89.50)' -> -8950. Raises ValueError if unparseable."""
    match = AMOUNT_RE.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"not an amount: {text!r}")
    return _from_match(match)


def _from_match(match: re.Match) -> int:
    value = int(match.group("whole").replace(",", "")) * 100 + int(match.group("cents"))
    negative = bool(match.group("sign")) or (match.group("paren") and match.group("close"))
    if match.group("trailing") in {"-", "CR"}:
        negative = not negative if match.group("trailing") == "-" else negative
    return -value if negative else value


def format_money(minor: int | None) -> str:
    """123456 -> '1234.56'. None -> ''. Plain decimal, no separators, for CSV."""
    if minor is None:
        return ""
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    return f"{sign}{minor // 100}.{minor % 100:02d}"
