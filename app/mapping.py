"""Profiles: map the varied headers real PDFs use onto one stable set of CSV columns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import yaml

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"

# A column matches a header at or above this similarity; below it we leave the
# column blank rather than guess.
DEFAULT_MIN_CONFIDENCE = 0.72


@dataclass
class Column:
    name: str
    aliases: list[str] = field(default_factory=list)
    type: str = "text"  # text | number | date
    required: bool = False

    @property
    def candidates(self) -> list[str]:
        return [self.name, *self.aliases]


@dataclass
class Profile:
    name: str
    columns: list[Column]
    description: str = ""
    match_text: list[str] = field(default_factory=list)
    min_confidence: float = DEFAULT_MIN_CONFIDENCE

    @classmethod
    def from_dict(cls, data: dict, fallback_name: str) -> "Profile":
        columns = []
        for raw in data.get("columns", []) or []:
            if isinstance(raw, str):
                columns.append(Column(name=raw))
                continue
            columns.append(
                Column(
                    name=raw["name"],
                    aliases=list(raw.get("aliases", []) or []),
                    type=raw.get("type", "text"),
                    required=bool(raw.get("required", False)),
                )
            )
        if not columns:
            raise ValueError(f"profile '{fallback_name}' defines no columns")
        return cls(
            name=data.get("name", fallback_name),
            description=data.get("description", ""),
            columns=columns,
            match_text=list(data.get("match_text", []) or []),
            min_confidence=float(data.get("min_confidence", DEFAULT_MIN_CONFIDENCE)),
        )


def load_profiles(directory: Path | str = PROFILE_DIR) -> list[Profile]:
    """Load every *.yaml profile in `directory`, sorted by name."""
    directory = Path(directory)
    profiles = []
    for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
        data = yaml.safe_load(path.read_text()) or {}
        profiles.append(Profile.from_dict(data, path.stem))
    return sorted(profiles, key=lambda p: p.name)


# --------------------------------------------------------------------------- #
# Header matching
# --------------------------------------------------------------------------- #

def normalise(text: str) -> str:
    """Lowercase, strip punctuation and filler words so headers compare fairly."""
    text = re.sub(r"[^a-z0-9]+", " ", str(text).lower())
    words = [w for w in text.split() if w not in {"the", "of", "no", "num", "nbr"}]
    return " ".join(words)


def similarity(a: str, b: str) -> float:
    left, right = normalise(a), normalise(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    # Substring containment ("amount" in "amount usd") is a strong signal that
    # ratio() alone under-scores on long headers.
    if left in right.split() or right in left.split():
        return 0.94
    if left in right or right in left:
        return 0.88
    if _is_abbreviation(left, right) or _is_abbreviation(right, left):
        return 0.80
    return SequenceMatcher(None, left, right).ratio()


def _is_abbreviation(short: str, long: str) -> bool:
    """True for contractions like qty/quantity: same letters, in order, much shorter."""
    if " " in short or len(short) < 3 or len(short) * 3 > len(long) * 2:
        return False
    it = iter(long)
    return all(char in it for char in short)


def match_columns(header: list[str], profile: Profile) -> dict[str, int | None]:
    """Best header index for each profile column, greedily, never reusing an index."""
    scores: list[tuple[float, str, int]] = []
    for column in profile.columns:
        for idx, cell in enumerate(header):
            best = max(similarity(candidate, cell) for candidate in column.candidates)
            if best >= profile.min_confidence:
                scores.append((best, column.name, idx))

    scores.sort(key=lambda s: -s[0])
    mapping: dict[str, int | None] = {c.name: None for c in profile.columns}
    used: set[int] = set()
    for _, column_name, idx in scores:
        if mapping[column_name] is None and idx not in used:
            mapping[column_name] = idx
            used.add(idx)
    return mapping


def score_profile(header: list[str], text: str, profile: Profile) -> float:
    """How well this profile fits a table: 0.0 (no fit) to 1.0."""
    mapping = match_columns(header, profile)
    required = [c for c in profile.columns if c.required]
    if required and any(mapping[c.name] is None for c in required):
        return 0.0

    matched = sum(1 for v in mapping.values() if v is not None)
    if not matched:
        return 0.0
    score = matched / len(profile.columns)

    if profile.match_text:
        haystack = normalise(text)
        hits = sum(1 for needle in profile.match_text if normalise(needle) in haystack)
        score = 0.7 * score + 0.3 * (hits / len(profile.match_text))
    return score


def choose_profile(
    header: list[str], text: str, profiles: list[Profile], threshold: float = 0.5
) -> tuple[Profile | None, float]:
    """Pick the best-fitting profile for a table, or (None, 0.0) if none fit."""
    best: tuple[Profile | None, float] = (None, 0.0)
    for profile in profiles:
        score = score_profile(header, text, profile)
        if score > best[1]:
            best = (profile, score)
    return best if best[1] >= threshold else (None, 0.0)


# --------------------------------------------------------------------------- #
# Value normalisation
# --------------------------------------------------------------------------- #

_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%d.%m.%Y", "%d/%m/%y", "%m/%d/%y",
)


def to_number(value: str) -> str:
    """Strip currency symbols and thousands separators; (123) means -123."""
    raw = value.strip()
    if not raw:
        return ""
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^\d.,\-]", "", raw.strip("()"))
    if not cleaned:
        return value
    # 1.234,56 (European) vs 1,234.56 (Anglo): the last separator is the decimal point.
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        decimals = cleaned.rsplit(",", 1)[1]
        cleaned = cleaned.replace(",", "." if len(decimals) in (1, 2) else "")
    try:
        number = float(cleaned)
    except ValueError:
        return value
    if negative:
        number = -number
    return f"{number:g}" if number != int(number) else str(int(number))


def to_date(value: str) -> str:
    """Normalise a recognised date to ISO YYYY-MM-DD; pass anything else through."""
    from datetime import datetime

    raw = re.sub(r"\s+", " ", value.strip())
    if not raw:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def coerce(value: str, column_type: str) -> str:
    if column_type == "number":
        return to_number(value)
    if column_type == "date":
        return to_date(value)
    return value
