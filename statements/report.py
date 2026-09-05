"""The two CSVs: every transaction, and the per-statement reconciliation report."""

from __future__ import annotations

import csv
from pathlib import Path

from .money import format_money
from .parse import StatementDoc
from .profiles import Direction
from .reconcile import StatementCheck

TRANSACTION_COLUMNS = [
    "source_file",
    "account_label",
    "page_number",
    "sheet_number",
    "statement_period_start",
    "statement_period_end",
    "txn_date",
    "type_code",
    "description",
    "paid_out",
    "paid_in",
    "amount",
    "currency",
    "foreign_amount",
    "foreign_currency",
    "running_balance",
    "direction_confidence",
    "reconciliation_note",
    # Appended after the agreed schema, so a loader reading by name is
    # unaffected. Card statements print both a transaction date and a posting
    # date; `txn_date` holds the former, this holds the latter.
    "posting_date",
    # Added for multi-account batches: where the row came from, whose it is,
    # how confident the date is, and whether it also appears elsewhere.
    "source_account",
    "account_id",
    "owner",
    "bank",
    "type_label",
    "date_confidence",
    "duplicate_group",
    "duplicate_of",
]

RECONCILIATION_COLUMNS = [
    "source_file",
    "opening_balance",
    "closing_balance",
    "computed_paid_in",
    "computed_paid_out",
    "printed_paid_in",
    "printed_paid_out",
    "check",
    "notes",
]


def transaction_rows(
    doc: StatementDoc, account_label: str, profile=None
) -> list[dict[str, str]]:
    # The bank's own code is kept verbatim in `type_code`; its meaning goes
    # alongside rather than replacing it.
    labels = {c.code: c.label for c in getattr(profile, "codes", ())}
    default = getattr(profile, "default_code", "")
    if default and default not in labels:
        labels[default] = "Purchase" if default == "PUR" else "Transaction"
    bank = getattr(profile, "bank", "")
    rows = []
    for txn in doc.transactions:
        out = txn.direction is Direction.OUT
        rows.append(
            {
                "source_file": doc.source_file,
                "account_label": account_label,
                "page_number": str(txn.page_number),
                "sheet_number": doc.sheet_number,
                "statement_period_start": doc.period_start.isoformat() if doc.period_start else "",
                "statement_period_end": doc.period_end.isoformat() if doc.period_end else "",
                "txn_date": txn.txn_date.isoformat() if txn.txn_date else "",
                "type_code": txn.type_code,
                "description": txn.description,
                "paid_out": format_money(txn.amount) if out else "",
                "paid_in": "" if out else format_money(txn.amount),
                # Signed to the workbook's convention: positive = money out.
                "amount": format_money(txn.signed),
                "currency": txn.currency or doc.currency,
                "foreign_amount": format_money(txn.foreign_amount),
                "foreign_currency": txn.foreign_currency,
                "running_balance": format_money(txn.printed_balance),
                "direction_confidence": txn.direction_confidence,
                "reconciliation_note": txn.reconciliation_note,
                "posting_date": txn.posting_date.isoformat() if txn.posting_date else "",
                "source_account": txn.source_account or account_label,
                "account_id": txn.account_id or doc.account,
                "owner": txn.owner or doc.owner,
                "bank": bank,
                "type_label": labels.get(txn.type_code, ""),
                "date_confidence": txn.date_confidence,
                "duplicate_group": txn.duplicate_group,
                "duplicate_of": txn.duplicate_of,
            }
        )
    return rows


def reconciliation_row(check: StatementCheck) -> dict[str, str]:
    return {
        "source_file": check.source_file,
        "opening_balance": format_money(check.opening_balance),
        "closing_balance": format_money(check.closing_balance),
        "computed_paid_in": format_money(check.computed_paid_in),
        "computed_paid_out": format_money(check.computed_paid_out),
        "printed_paid_in": format_money(check.printed_paid_in),
        "printed_paid_out": format_money(check.printed_paid_out),
        "check": check.status,
        "notes": " | ".join(check.notes),
    }


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
