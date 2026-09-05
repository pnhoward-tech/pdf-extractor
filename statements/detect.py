"""Picking the right profile for a statement, without being told which.

Every profile already describes what its statements look like — the header that
opens the transaction table, the labels in the summary box, the vocabulary of
type codes. Scoring a document against those descriptions is enough to
recognise it, so no separate signature has to be maintained alongside them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .layout import Page
from .profiles import PROFILES, Profile

# Below this, a profile is not a credible match and inference takes over.
MATCH_THRESHOLD = 0.45

# The summary box is the strongest signal: its labels are specific to a bank
# and they appear whether or not the statement has any transactions.
WEIGHTS = {"summary": 0.45, "table": 0.25, "codes": 0.20, "period": 0.10}


@dataclass
class Match:
    profile: Profile
    score: float
    detail: dict[str, float]

    def explain(self) -> str:
        parts = ", ".join(f"{k} {v:.0%}" for k, v in self.detail.items())
        return f"{self.profile.name} ({self.score:.0%}: {parts})"


def score_profile(pages: list[Page], profile: Profile) -> Match:
    text = "\n".join(page.text for page in pages)
    detail: dict[str, float] = {}

    if profile.summary_patterns:
        hits = sum(1 for p in profile.summary_patterns.values() if p.search(text))
        detail["summary"] = hits / len(profile.summary_patterns)
    else:
        detail["summary"] = 0.0

    # Anchored per line: these patterns start with ^, which would never match
    # inside the joined text of a whole document.
    anchors = [*profile.table_start, *profile.table_continues]
    detail["table"] = 1.0 if any(page.find(p) is not None for p in anchors
                                 for page in pages) else 0.0

    if profile.codes:
        # Only count codes seen at the start of a line's content, so a code
        # spelled out inside a merchant name does not vote for a profile.
        seen = sum(1 for code in profile.codes if _code_appears(pages, profile, code.code))
        detail["codes"] = min(1.0, seen / min(len(profile.codes), 4))
    else:
        detail["codes"] = 0.0

    detail["period"] = (
        1.0 if profile.period_pattern and profile.period_pattern.search(text) else 0.0
    )

    score = sum(WEIGHTS[key] * value for key, value in detail.items())
    return Match(profile=profile, score=score, detail=detail)


def _code_appears(pages: list[Page], profile: Profile, code: str) -> bool:
    for page in pages:
        for line in page.lines:
            stripped = line.stripped
            if not stripped:
                continue
            if profile.date_pattern is not None:
                match = profile.date_pattern.match(line.text)
                if match:
                    stripped = line.text[match.end() :].strip()
            if profile.match_code(stripped) is not None and stripped.upper().startswith(
                code.upper().split()[0]
            ):
                return True
    return False


def detect(pages: list[Page], candidates: dict[str, Profile] | None = None) -> list[Match]:
    """Every profile scored against this document, best first."""
    pool = (candidates or PROFILES).values()
    return sorted((score_profile(pages, p) for p in pool), key=lambda m: -m.score)


def best_match(pages: list[Page]) -> Match | None:
    """The profile that fits, or None when nothing does well enough."""
    ranked = detect(pages)
    if ranked and ranked[0].score >= MATCH_THRESHOLD:
        return ranked[0]
    return None
