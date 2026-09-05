"""Finding the same transaction twice.

A card payment appears on the card statement as a purchase and on the bank
statement as the direct debit that settled the card; a transfer between two of
your own accounts appears in both. Nothing is deleted — every row is kept and
tagged, because which copy to keep is a judgement about the books, not about
the documents.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .parse import Transaction

# How far apart two records of the same movement can be dated. A card purchase
# and its bank settlement are usually days apart.
DEFAULT_WINDOW_DAYS = 5
# How alike two descriptions must be to count as the same merchant.
DESCRIPTION_SIMILARITY = 0.6

_NOISE = re.compile(r"\b(ltd|limited|plc|inc|llc|the|and|co|uk|gb|com|www)\b", re.I)
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def fingerprint(text: str) -> frozenset[str]:
    """Reduce a description to the words that identify the merchant."""
    cleaned = _NON_WORD.sub(" ", _NOISE.sub(" ", text.lower()))
    return frozenset(word for word in cleaned.split() if len(word) > 2)


def similarity(left: str, right: str) -> float:
    a, b = fingerprint(left), fingerprint(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


@dataclass
class DuplicateGroup:
    key: str
    transactions: list[Transaction]

    @property
    def accounts(self) -> set[str]:
        return {t.source_key for t in self.transactions}


def find_duplicates(
    transactions: list[Transaction],
    window_days: int = DEFAULT_WINDOW_DAYS,
    across_accounts_only: bool = True,
) -> list[DuplicateGroup]:
    """Group transactions that look like records of one movement of money.

    Matching is on amount and currency first — those must agree exactly — then
    on date proximity and merchant similarity. By default only matches spanning
    two different accounts are reported, since the same amount twice on one
    statement is usually two real purchases.
    """
    buckets: dict[tuple[int, str], list[Transaction]] = defaultdict(list)
    for txn in transactions:
        if txn.amount:
            buckets[(txn.amount, txn.currency)].append(txn)

    groups: list[DuplicateGroup] = []
    for (amount, currency), candidates in buckets.items():
        if len(candidates) < 2:
            continue
        for group in _cluster(candidates, window_days):
            if len(group) < 2:
                continue
            if across_accounts_only and len({t.source_key for t in group}) < 2:
                continue
            groups.append(DuplicateGroup(key=f"{currency}{amount}-{len(groups) + 1}", transactions=group))
    return groups


def _cluster(candidates: list[Transaction], window_days: int) -> list[list[Transaction]]:
    """Single-link clustering on date proximity and description similarity."""
    ordered = sorted(candidates, key=lambda t: (t.txn_date or _EARLIEST, t.source_key))
    clusters: list[list[Transaction]] = []
    for txn in ordered:
        for cluster in clusters:
            if any(_matches(txn, other, window_days) for other in cluster):
                cluster.append(txn)
                break
        else:
            clusters.append([txn])
    return clusters


def _matches(left: Transaction, right: Transaction, window_days: int) -> bool:
    if left.txn_date is None or right.txn_date is None:
        return False
    if abs((left.txn_date - right.txn_date).days) > window_days:
        return False
    # An identical amount on the same day across two accounts is worth flagging
    # even when the two banks describe it completely differently — which is the
    # usual case for a card settled by direct debit.
    if left.txn_date == right.txn_date and left.source_key != right.source_key:
        return True
    return similarity(left.description, right.description) >= DESCRIPTION_SIMILARITY


from datetime import date as _date  # noqa: E402 - used only as a sort fallback

_EARLIEST = _date.min


def annotate(transactions: list[Transaction], **kwargs) -> list[DuplicateGroup]:
    """Tag each transaction in a duplicate group, in place."""
    groups = find_duplicates(transactions, **kwargs)
    for group in groups:
        others = {t.source_key for t in group.transactions}
        for txn in group.transactions:
            txn.duplicate_group = group.key
            elsewhere = sorted(others - {txn.source_key})
            txn.duplicate_of = ", ".join(elsewhere)
    return groups
