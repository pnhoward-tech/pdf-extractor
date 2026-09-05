"""The web app.

Two tools behind one server:

* `/` — the bank statement extractor. Statements in, a reconciliation report
  and a transaction CSV out. This is the one to use for statements: the
  validation is the point of it.
* `/tables` — the general table extractor, for pulling tables out of any
  text-based PDF where no reconciliation is possible.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .mapping import load_profiles
from .pipeline import process_batch
from .statements_api import looks_like_pdf, router as statements_router

MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per PDF
MAX_FILES = 200
PREVIEW_ROWS = 200

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Statement & Table Extractor", version="0.2.0")
app.include_router(statements_router)

# Completed jobs, keyed by id, holding the generated CSV ready for download.
# In-memory on purpose: results are disposable and never touch disk.
_jobs: dict[str, dict[str, str]] = {}


@app.get("/api/tables/profiles")
def list_profiles() -> dict:
    return {
        "profiles": [
            {
                "name": p.name,
                "description": p.description,
                "columns": [c.name for c in p.columns],
            }
            for p in load_profiles()
        ]
    }


@app.post("/api/tables/extract")
async def extract(
    files: list[UploadFile],
    profile: str = Form("auto"),
    include_unmatched: bool = Form(True),
) -> dict:
    if not files:
        raise HTTPException(400, "No files uploaded.")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Too many files (limit {MAX_FILES}).")

    sources: list[tuple[str, bytes]] = []
    for upload in files:
        data = await upload.read()
        name = Path(upload.filename or "unnamed.pdf").name
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{name} is larger than {MAX_FILE_BYTES // 1024 // 1024} MB.")
        if not looks_like_pdf(data):
            raise HTTPException(415, f"{name} does not look like a PDF.")
        sources.append((name, data))

    try:
        result = process_batch(
            sources, forced_profile_name=profile, include_unmatched=include_unmatched
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"csv": result.to_csv()}
    # Keep memory bounded; only the most recent handful of jobs stay downloadable.
    for stale in list(_jobs)[:-20]:
        _jobs.pop(stale, None)

    payload = result.as_dict()
    payload["rows"] = payload["rows"][:PREVIEW_ROWS]
    payload["truncated"] = result.row_count > PREVIEW_ROWS
    payload["job_id"] = job_id
    return payload


@app.get("/api/tables/download/{job_id}")
def download(job_id: str) -> PlainTextResponse:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "That result has expired — please extract again.")
    return PlainTextResponse(
        job["csv"],
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="extracted.csv"'},
    )


@app.get("/")
def index() -> FileResponse:
    """The statement extractor."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/tables")
def tables() -> FileResponse:
    """The general table extractor."""
    return FileResponse(STATIC_DIR / "tables.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
