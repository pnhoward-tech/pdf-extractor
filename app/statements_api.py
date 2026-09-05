"""Web API over the statement extractor.

Uploads land in a temporary directory because the pipeline shells out to
poppler and tesseract, which need real files; the directory is removed as soon
as the batch has been read. Results live in memory only — statements are
somebody's finances, and this is a tool you run on your own machine.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from statements import batch
from statements.money import format_money
from statements.profiles import PROFILES, get_profile
from statements.report import (
    RECONCILIATION_COLUMNS,
    TRANSACTION_COLUMNS,
    reconciliation_row,
    transaction_rows,
    write_csv,
)

def looks_like_pdf(data: bytes) -> bool:
    """Accept a PDF whose header is not at byte zero.

    Real statements do turn up with leading whitespace before "%PDF-", and
    readers scan the head of the file rather than requiring offset zero, so
    rejecting them would refuse files poppler opens quite happily.
    """
    return b"%PDF-" in data[:1024]


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILES = 200
PREVIEW_ROWS = 500

router = APIRouter(prefix="/api/statements")


@dataclass
class Job:
    transactions_csv: str
    reconciliation_csv: str
    row_count: int = 0
    files: list[str] = field(default_factory=list)


_jobs: dict[str, Job] = {}


@router.get("/profiles")
def list_profiles() -> dict:
    return {
        "profiles": [
            {
                "name": p.name,
                "bank": p.bank,
                "description": p.description,
                "currency": p.currency,
                "liability": p.is_liability,
            }
            for p in sorted(PROFILES.values(), key=lambda p: p.name)
        ]
    }


@router.post("/extract")
async def extract(
    files: list[UploadFile],
    account_label: str = Form(""),
    profile: str = Form("auto"),
    ocr: bool = Form(False),
    dedupe: bool = Form(True),
    duplicate_window: int = Form(5),
) -> dict:
    if not files:
        raise HTTPException(400, "No files uploaded.")
    if profile != "auto":
        # A profile name that does not exist is a bad request, not a failure of
        # each individual statement.
        try:
            get_profile(profile)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Too many files (limit {MAX_FILES}).")

    workdir = Path(tempfile.mkdtemp(prefix="statements-"))
    try:
        paths = []
        for upload in files:
            data = await upload.read()
            name = Path(upload.filename or "unnamed.pdf").name
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, f"{name} is larger than 50 MB.")
            if not looks_like_pdf(data):
                raise HTTPException(415, f"{name} does not look like a PDF.")
            path = workdir / name
            path.write_bytes(data)
            paths.append(path)

        try:
            result = batch.run(
                sorted(paths),
                profile=profile,
                account_label=account_label,
                ocr=ocr,
                dedupe=dedupe,
                duplicate_window=duplicate_window,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        return _payload(result, account_label)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _payload(result: batch.Batch, account_label: str) -> dict:
    rows, held_back = [], []
    for outcome in result.outcomes:
        outcome_rows = transaction_rows(outcome.doc, account_label, outcome.profile)
        # Rows from a statement that does not reconcile are still returned, so
        # they can be inspected, but they are marked and excluded from the
        # download unless the reader asks for them.
        for row in outcome_rows:
            row["_reconciled"] = "yes" if outcome.ok else "no"
        rows.extend(outcome_rows)
        if not outcome.ok:
            held_back.append(outcome.source_file)

    passing = [r for r in rows if r["_reconciled"] == "yes"]
    job_id = uuid.uuid4().hex
    _jobs[job_id] = Job(
        transactions_csv=_csv(TRANSACTION_COLUMNS, passing),
        reconciliation_csv=_csv(
            RECONCILIATION_COLUMNS, [reconciliation_row(o.check) for o in result.outcomes]
        ),
        row_count=len(passing),
        files=[o.source_file for o in result.outcomes],
    )
    for stale in list(_jobs)[:-10]:
        _jobs.pop(stale, None)

    return {
        "job_id": job_id,
        "statements": [_statement(o) for o in result.outcomes],
        "errors": [{"file": name, "message": message} for name, message in result.errors],
        "continuity": result.continuity,
        "duplicates": [
            {"key": g.key, "accounts": sorted(g.accounts), "count": len(g.transactions)}
            for g in result.duplicates
        ],
        "columns": TRANSACTION_COLUMNS,
        "rows": rows[:PREVIEW_ROWS],
        "row_count": len(rows),
        "shipped_count": len(passing),
        "truncated": len(rows) > PREVIEW_ROWS,
        "held_back": held_back,
    }


def _statement(outcome: batch.FileOutcome) -> dict:
    check, doc = outcome.check, outcome.doc
    return {
        "source_file": outcome.source_file,
        "profile": outcome.profile.name,
        "bank": outcome.profile.bank,
        "inferred": outcome.inferred,
        "selection": outcome.selection,
        "liability": outcome.profile.is_liability,
        "currency": doc.currency,
        "owner": doc.owner,
        "account_id": doc.account,
        "period_start": doc.period_start.isoformat() if doc.period_start else "",
        "period_end": doc.period_end.isoformat() if doc.period_end else "",
        "opening_balance": format_money(check.opening_balance),
        "closing_balance": format_money(check.closing_balance),
        "computed_paid_in": format_money(check.computed_paid_in),
        "computed_paid_out": format_money(check.computed_paid_out),
        "printed_paid_in": format_money(check.printed_paid_in),
        "printed_paid_out": format_money(check.printed_paid_out),
        "transaction_count": len(doc.transactions),
        "ocr": doc.ocr,
        "check": check.status,
        "ok": check.ok,
        "notes": check.notes,
        "warnings": doc.warnings,
    }


def _csv(columns: list[str], rows: list[dict[str, str]]) -> str:
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@router.get("/download/{job_id}/{which}")
def download(job_id: str, which: str) -> PlainTextResponse:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "That result has expired — please extract again.")
    if which not in {"transactions", "reconciliation"}:
        raise HTTPException(404, "No such file.")
    body = job.transactions_csv if which == "transactions" else job.reconciliation_csv
    return PlainTextResponse(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{which}.csv"'},
    )


def save_to(directory: Path, job_id: str) -> None:
    """Write a finished job's CSVs to disk (used by tests and scripting)."""
    job = _jobs[job_id]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "transactions.csv").write_text(job.transactions_csv, encoding="utf-8")
    (directory / "reconciliation.csv").write_text(job.reconciliation_csv, encoding="utf-8")
