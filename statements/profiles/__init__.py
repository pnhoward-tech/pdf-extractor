"""Bank profiles. Each describes one statement layout: where the transaction
table starts and stops, how to read the summary box, and how to read a line.

Deriving a new one: dump a page with `python -m statements.cli dump file.pdf
--page 2` and read the columns off it. Start from the profile whose bank and
account type is closest.
"""

from __future__ import annotations

from .base import Direction, Profile, TypeCode
from .hsbc_uk import HSBC_UK_PREMIER
from .hsbc_uk_card import HSBC_UK_CARD
from .hsbc_us import HSBC_US_PREMIER
from .whitaker_us import WHITAKER_US

PROFILES: dict[str, Profile] = {
    p.name: p for p in (HSBC_US_PREMIER, HSBC_UK_PREMIER, HSBC_UK_CARD, WHITAKER_US)
}

DEFAULT_PROFILE = HSBC_US_PREMIER.name


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; known profiles: {known}") from None


__all__ = ["PROFILES", "DEFAULT_PROFILE", "Profile", "TypeCode", "Direction", "get_profile"]
