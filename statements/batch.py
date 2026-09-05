"""One run over a folder of statements, shared by the CLI and the web app.

Everything that decides what the output says lives here — which profile reads
each file, whether its dates hold up, whether it balances, and which rows appear
in more than one account — so the two front ends cannot drift apart on any of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .dates import DateReport, check_dates
from .dedupe import DuplicateGroup, annotate
from .detect import MATCH_THRESHOLD, detect
from .infer import InferenceFailed, infer_profile
from .layout import load_pages, split_pages
from .ocr import has_text_layer, ocr_pdf
from .parse import StatementDoc, parse_statement
from .profiles import Profile, get_profile
from .reconcile import StatementCheck, check_sheet_continuity, reconcile


@dataclass
class FileOutcome:
    """What happened to one statement."""

    source_file: str
    profile: Profile
    doc: StatementDoc
    check: StatementCheck
    dates: DateReport
    selection: str  # how the profile was chosen, for the report
    inferred: bool = False

    @property
    def ok(self) -> bool:
        return self.check.ok


@dataclass
class Batch:
    outcomes: list[FileOutcome] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)
    continuity: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.ok]

    @property
    def failed(self) -> list[FileOutcome]:
        return [o for o in self.outcomes if not o.ok]

    def transactions(self, include_failed: bool = False):
        for outcome in self.outcomes:
            if outcome.ok or include_failed:
                yield outcome, outcome.doc.transactions


def load_document_pages(pdf: Path, ocr: bool):
    """Layout text for a PDF, falling back to OCR only when asked."""
    if ocr and not has_text_layer(pdf):
        return split_pages(ocr_pdf(pdf))
    return load_pages(pdf)


def choose_profile(pdf: Path, requested: str, ocr: bool) -> tuple[Profile, str, bool]:
    """The profile for one PDF, with a sentence saying how it was chosen."""
    if requested and requested != "auto":
        profile = get_profile(requested)
        return profile, f"forced to {profile.name}", False

    pages = load_document_pages(pdf, ocr)
    ranked = detect(pages)
    if ranked and ranked[0].score >= MATCH_THRESHOLD:
        return ranked[0].profile, f"matched {ranked[0].explain()}", False

    runner_up = ranked[0].explain() if ranked else "nothing"
    try:
        profile, notes = infer_profile(pages, name=f"inferred-{pdf.stem[:20]}")
    except InferenceFailed as exc:
        raise ValueError(
            f"No profile fits and one could not be inferred — {exc} "
            f"(closest was {runner_up})."
        ) from exc
    return profile, "inferred from the document: " + "; ".join(notes), True


def run(
    pdfs: list[Path],
    *,
    profile: str = "auto",
    account_label: str = "",
    ocr: bool = False,
    dedupe: bool = True,
    duplicate_window: int = 5,
) -> Batch:
    """Parse, validate and cross-check a batch of statements."""
    batch = Batch()

    for pdf in pdfs:
        try:
            chosen, selection, inferred = choose_profile(pdf, profile, ocr)
            doc = parse_statement(pdf, chosen, ocr=ocr)
        except Exception as exc:  # a bad file must not take the batch down
            batch.errors.append((Path(pdf).name, str(exc)))
            continue

        # Section-organised statements group by kind, not date, so their
        # ordering proves nothing about how the dates were read.
        dates = check_dates(doc, chronological=not chosen.section_patterns)
        doc.warnings.extend(dates.notes)

        check = reconcile(doc, liability=chosen.is_liability)
        # Reconciliation proves the amounts; the date check is the other half,
        # and a statement is only sound when both hold.
        if not dates.ok:
            check.ok = False
            check.notes.extend(dates.notes)

        for txn in doc.transactions:
            txn.currency = txn.currency or doc.currency
            txn.source_account = txn.source_account or account_label or doc.account

        batch.outcomes.append(
            FileOutcome(
                source_file=doc.source_file,
                profile=chosen,
                doc=doc,
                check=check,
                dates=dates,
                selection=selection,
                inferred=inferred,
            )
        )

    if dedupe:
        every = [t for o in batch.outcomes for t in o.doc.transactions]
        batch.duplicates = annotate(every, window_days=duplicate_window)
    batch.continuity = check_sheet_continuity([o.doc for o in batch.outcomes])
    return batch
