"""Batch pipeline: PDFs in, one normalised CSV out."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .extract import Document, RawTable, extract_document
from .mapping import Profile, choose_profile, coerce, load_profiles, match_columns

META_COLUMNS = ["source_file", "page", "table", "profile"]


@dataclass
class TableResult:
    page: int
    table: int
    profile: str
    confidence: float
    header: list[str]
    matched: dict[str, str | None]  # output column -> source header it came from
    row_count: int


@dataclass
class FileResult:
    filename: str
    tables: list[TableResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None


@dataclass
class BatchResult:
    columns: list[str]
    rows: list[dict[str, str]]
    files: list[FileResult]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_csv(self) -> str:
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=self.columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(self.rows)
        return buffer.getvalue()

    def as_dict(self) -> dict:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "files": [asdict(f) for f in self.files],
        }


def _map_table(table: RawTable, profile: Profile) -> tuple[list[dict[str, str]], dict[str, str | None]]:
    """Project a raw table onto the profile's columns."""
    mapping = match_columns(table.header, profile)
    matched = {
        name: table.header[idx] if idx is not None else None for name, idx in mapping.items()
    }
    rows = []
    for raw_row in table.rows:
        row = {}
        for column in profile.columns:
            idx = mapping[column.name]
            value = raw_row[idx] if idx is not None and idx < len(raw_row) else ""
            row[column.name] = coerce(value, column.type)
        if any(row.values()):
            rows.append(row)
    return rows, matched


def _passthrough_table(table: RawTable) -> tuple[list[dict[str, str]], dict[str, str | None]]:
    """No profile matched: emit the table's own headers verbatim."""
    header = _dedupe(table.header)
    matched = {name: name for name in header}
    rows = [
        row
        for row in ({h: r[i] if i < len(r) else "" for i, h in enumerate(header)} for r in table.rows)
        if any(row.values())
    ]
    return rows, matched


def _dedupe(header: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for name in header:
        name = name or "column"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        result.append(name)
    return result


def process_document(
    doc: Document,
    profiles: list[Profile],
    forced_profile: Profile | None = None,
    include_unmatched: bool = True,
) -> tuple[list[dict[str, str]], FileResult]:
    """Map every table in one document, returning CSV-ready rows plus a report."""
    report = FileResult(filename=doc.filename, warnings=list(doc.warnings))
    all_rows: list[dict[str, str]] = []

    for table in doc.tables:
        if forced_profile is not None:
            profile, confidence = forced_profile, 1.0
        else:
            profile, confidence = choose_profile(table.header, doc.text, profiles)

        if profile is not None:
            rows, matched = _map_table(table, profile)
            profile_name = profile.name
        elif include_unmatched:
            rows, matched = _passthrough_table(table)
            profile_name = "(raw headers)"
        else:
            continue

        meta = {
            "source_file": doc.filename,
            "page": str(table.page),
            "table": str(table.index + 1),
            "profile": profile_name,
        }
        all_rows.extend({**meta, **row} for row in rows)
        report.tables.append(
            TableResult(
                page=table.page,
                table=table.index + 1,
                profile=profile_name,
                confidence=round(confidence, 3),
                header=table.header,
                matched=matched,
                row_count=len(rows),
            )
        )

    report.row_count = len(all_rows)
    if doc.tables and not all_rows:
        report.warnings.append("Tables were detected but no data rows survived mapping.")
    return all_rows, report


def process_batch(
    sources: list[tuple[str, bytes]],
    profiles: list[Profile] | None = None,
    forced_profile_name: str | None = None,
    include_unmatched: bool = True,
) -> BatchResult:
    """Run the whole batch. `sources` is a list of (filename, pdf_bytes)."""
    profiles = load_profiles() if profiles is None else profiles
    forced = None
    if forced_profile_name and forced_profile_name != "auto":
        forced = next((p for p in profiles if p.name == forced_profile_name), None)
        if forced is None:
            raise ValueError(f"unknown profile: {forced_profile_name}")

    rows: list[dict[str, str]] = []
    files: list[FileResult] = []
    for filename, data in sources:
        try:
            doc = extract_document(data, filename=filename)
        except Exception as exc:
            files.append(FileResult(filename=filename, error=f"Could not read PDF: {exc}"))
            continue
        file_rows, report = process_document(doc, profiles, forced, include_unmatched)
        rows.extend(file_rows)
        files.append(report)

    # Column order: metadata, then profile columns in declaration order, then any
    # extras that passthrough tables contributed.
    columns = list(META_COLUMNS)
    for profile in profiles:
        if forced is not None and profile is not forced:
            continue
        for column in profile.columns:
            if column.name not in columns:
                columns.append(column.name)
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    used = {key for row in rows for key in row}
    columns = [c for c in columns if c in META_COLUMNS or c in used]
    return BatchResult(columns=columns, rows=rows, files=files)


def process_paths(paths: list[str | Path], **kwargs) -> BatchResult:
    """Convenience wrapper for the CLI: read PDFs from disk and process them."""
    sources = [(Path(p).name, Path(p).read_bytes()) for p in paths]
    return process_batch(sources, **kwargs)
