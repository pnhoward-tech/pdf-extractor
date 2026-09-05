"""Command-line entry point.

    python -m statements.cli extract ./statements --account-label CUR1 -o ./out
    python -m statements.cli dump statement.pdf --page 2
    python -m statements.cli profiles
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dates import check_dates
from .dedupe import annotate
from .detect import MATCH_THRESHOLD, detect
from .infer import InferenceFailed, infer_profile
from .layout import PopplerMissing, load_pages, split_pages
from .ocr import TesseractMissing
from .money import format_money
from .parse import parse_statement
from .profiles import DEFAULT_PROFILE, PROFILES, get_profile
from .reconcile import check_sheet_continuity, reconcile
from .report import (
    RECONCILIATION_COLUMNS,
    TRANSACTION_COLUMNS,
    reconciliation_row,
    transaction_rows,
    write_csv,
)


def collect_pdfs(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.pdf")))
        elif path.exists():
            paths.append(path)
        else:
            print(f"  ! not found: {path}", file=sys.stderr)
    return paths


def resolve_profile(pdf: Path, requested: str, ocr: bool) -> tuple[object, str]:
    """Choose the profile for one PDF: the named one, the best-scoring one, or
    a profile inferred from the document when nothing known fits."""
    if requested != "auto":
        return get_profile(requested), ""

    from .ocr import has_text_layer, ocr_pdf

    pages = split_pages(ocr_pdf(pdf)) if (ocr and not has_text_layer(pdf)) else load_pages(pdf)
    ranked = detect(pages)
    if ranked and ranked[0].score >= MATCH_THRESHOLD:
        return ranked[0].profile, f"matched {ranked[0].explain()}"
    try:
        profile, notes = infer_profile(pages, name=f"inferred-{pdf.stem[:20]}")
    except InferenceFailed as exc:
        raise ValueError(
            f"{pdf.name}: no profile fits and one could not be inferred — {exc}\n"
            f"  Best guess was {ranked[0].explain() if ranked else 'nothing'}.\n"
            f"  Run: python -m statements.cli learn {pdf} --ocr" if ocr else
            f"  Run: python -m statements.cli learn {pdf}"
        ) from exc
    return profile, "INFERRED (no known profile fits): " + "; ".join(notes)


def cmd_extract(args: argparse.Namespace) -> int:
    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        print("No PDFs found.", file=sys.stderr)
        return 1

    docs, checks, profiles, chosen = [], [], [], []
    for pdf in pdfs:
        profile, why = resolve_profile(pdf, args.profile, args.ocr)
        doc = parse_statement(pdf, profile, ocr=args.ocr)
        report = check_dates(doc, chronological=not profile.section_patterns)
        doc.warnings.extend(report.notes)
        check = reconcile(doc, liability=profile.is_liability)
        if report.outside_period or any("out of date order" in n for n in report.notes):
            check.ok = False
            check.notes.extend(report.notes)
        docs.append(doc)
        checks.append(check)
        profiles.append(profile)
        if why:
            chosen.append(f"  {pdf.name}: {why}")

    all_txns = [t for doc in docs for t in doc.transactions]
    for doc, label in zip(docs, [args.account_label] * len(docs)):
        for txn in doc.transactions:
            txn.currency = txn.currency or doc.currency
            txn.source_account = txn.source_account or label or doc.account
    duplicates = annotate(all_txns, window_days=args.duplicate_window) if not args.no_dedupe else []

    profile = profiles[0]

    # The reconciliation report is the thing to read first, so print it first.
    if chosen:
        print("\nProfile selection")
        for line in chosen:
            print(line)
    banks = sorted({p.bank for p in profiles})
    print(f"\nReconciliation — {', '.join(banks)}\n")
    movement = "owed" if profile.is_liability else "close"
    header = f"{'statement':<34}{'open':>11}{'in':>10}{'out':>11}{movement:>11}   check"
    print(header)
    print("-" * len(header))
    for check in checks:
        print(
            f"{check.source_file[:33]:<34}"
            f"{format_money(check.opening_balance):>11}"
            f"{format_money(check.computed_paid_in):>10}"
            f"{format_money(check.computed_paid_out):>11}"
            f"{format_money(check.closing_balance):>11}"
            f"   {check.status}"
        )
    for check in checks:
        for note in check.notes:
            print(f"  ! {check.source_file}: {note}", file=sys.stderr)
    for doc in docs:
        for warning in doc.warnings:
            print(f"  ~ {doc.source_file}: {warning}", file=sys.stderr)
    for warning in check_sheet_continuity(docs):
        print(f"  ~ {warning}", file=sys.stderr)

    passed = {c.source_file for c in checks if c.ok}
    failed = [c.source_file for c in checks if not c.ok]

    rows = []
    for doc, doc_profile in zip(docs, profiles):
        if doc.source_file in passed or args.include_failed:
            rows.extend(transaction_rows(doc, args.account_label, doc_profile))

    out_dir = Path(args.output)
    write_csv(out_dir / "transactions.csv", TRANSACTION_COLUMNS, rows)
    write_csv(
        out_dir / "reconciliation.csv",
        RECONCILIATION_COLUMNS,
        [reconciliation_row(c) for c in checks],
    )

    if duplicates:
        print(
            f"\n{len(duplicates)} transaction(s) appear in more than one account "
            "— tagged in duplicate_group, not removed."
        )
    print(f"\n{len(passed)}/{len(checks)} statements reconcile.")
    print(f"Wrote {len(rows)} transactions to {out_dir / 'transactions.csv'}")
    print(f"Wrote the reconciliation report to {out_dir / 'reconciliation.csv'}")
    if failed:
        listed = ", ".join(failed)
        if args.include_failed:
            print(f"\nWARNING: included rows from statements that do NOT reconcile: {listed}")
        else:
            print(f"\nHELD BACK (did not reconcile): {listed}")
            print("Investigate these before trusting their rows; --include-failed ships them anyway.")
        return 2
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    """Print layout text with column rulers — the first thing to reach for when
    a page parses to nothing."""
    if args.ocr:
        from .layout import split_pages
        from .ocr import ocr_pdf

        pages = split_pages(ocr_pdf(args.pdf))
    else:
        pages = load_pages(args.pdf)
    for page in pages:
        if args.page and page.number != args.page:
            continue
        print(f"\n{'=' * 30} PAGE {page.number} {'=' * 30}")
        if args.ruler:
            tens = "".join(str(i // 10 % 10) * 10 for i in range(0, 160, 10))
            print(f"     |{tens}")
            print(f"     |{'0123456789' * 16}")
        for line in page.lines:
            if line.stripped or not args.skip_blank:
                print(f"{line.number:4d} |{line.text}")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    """Infer a profile for an unfamiliar statement and print what it found.

    The output is a starting point to save into statements/profiles/ and
    refine — not a finished profile. The reconciliation report is what tells
    you which parts still need work.
    """
    from .ocr import has_text_layer, ocr_pdf

    pdf = Path(args.pdf)
    pages = split_pages(ocr_pdf(pdf)) if (args.ocr and not has_text_layer(pdf)) else load_pages(pdf)

    ranked = detect(pages)
    print("\nHow this document scores against the profiles that already exist:")
    for match in ranked[:4]:
        print(f"  {match.explain()}")
    if ranked and ranked[0].score >= MATCH_THRESHOLD:
        print(f"\n{ranked[0].profile.name} already fits. Use: -p {ranked[0].profile.name}")
        return 0

    try:
        profile, notes = infer_profile(pages, name=pdf.stem[:24])
    except InferenceFailed as exc:
        print(f"\nCould not infer a profile: {exc}", file=sys.stderr)
        return 1

    print("\nInferred from the document itself:")
    for note in notes:
        print(f"  {note}")

    doc = parse_statement(pdf, profile, ocr=args.ocr)
    check = reconcile(doc, liability=profile.is_liability)
    print(
        f"\nA trial run with it reads {len(doc.transactions)} transactions and "
        f"reconciles: {check.status}."
    )
    for note in check.notes[:4]:
        print(f"  ! {note}")
    if not check.ok:
        print(
            "\nThat is the inference telling you what it did not work out. The "
            "usual gaps are the summary-box wordings and multi-line transactions."
        )
    print(f"\nDraft profile — save as statements/profiles/{pdf.stem[:24].lower()}.py:\n")
    print(_render_profile(profile, notes))
    return 0


def _render_profile(profile, notes: list[str]) -> str:
    codes = "\n".join(
        f'        TypeCode("{c.code}", Direction.AMBIGUOUS, ""),' for c in profile.codes
    )
    summary = "\n".join(
        f'        "{field}": re.compile(r"{pattern.pattern}", re.I),'
        for field, pattern in profile.summary_patterns.items()
    )
    stops = "\n".join(f'        re.compile(r"{p.pattern}", re.I),' for p in profile.table_stop)
    starts = "\n".join(f'        re.compile(r"{p.pattern}", re.I),' for p in profile.table_start)
    detail = "\n".join(f"#   {n}" for n in notes)
    return f'''"""Inferred profile — review before trusting a batch.

Read off the document:
{detail}

Check first: the direction of each type code (mark anything that can post
either way Direction.AMBIGUOUS), the summary-box patterns, and whether the
account is an asset or a liability.
"""

import re
from datetime import datetime

from .base import Direction, Profile, TypeCode

PROFILE = Profile(
    name="{profile.name}",
    bank="TODO",
    description="TODO",
    currency="{profile.currency}",
    table_start=[
{starts}
    ],
    table_stop=[
{stops}
    ],
    summary_patterns={{
{summary}
    }},
    date_pattern=re.compile(r"{profile.date_pattern.pattern}"),
    parse_date=lambda t: datetime.strptime(" ".join(t.split()), "TODO_FORMAT").date(),
    date_starts_transaction={profile.date_starts_transaction},
    code_source="{profile.code_source}",
    codes=(
{codes}
    ),
    balance_marker="{profile.balance_marker}",
    balance_sign="asset",
    description_max_col={profile.description_max_col},
    amount_band_width={profile.amount_band_width},
    balance_min_col={profile.balance_min_col},
    default_in_out_split={profile.default_in_out_split},
    paid_in_side="{profile.paid_in_side}",
)
'''


def cmd_profiles(_: argparse.Namespace) -> int:
    for name, profile in sorted(PROFILES.items()):
        print(f"{name:<10} {profile.currency}  {profile.bank} — {profile.description}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="statements", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="parse a folder of statements into CSVs")
    extract.add_argument("inputs", nargs="+", help="statement PDFs, or folders of them")
    extract.add_argument("-o", "--output", default="out", help="output folder (default: out)")
    extract.add_argument(
        "-a", "--account-label", default="", help="channel code for these statements, e.g. CUR1"
    )
    extract.add_argument(
        "-p", "--profile", default="auto",
        help="bank profile, or 'auto' to detect it (default: auto)",
    )
    extract.add_argument(
        "--no-dedupe", action="store_true", help="skip cross-account duplicate detection"
    )
    extract.add_argument(
        "--duplicate-window", type=int, default=5,
        help="days apart two records of one movement may be dated (default: 5)",
    )
    extract.add_argument(
        "--ocr",
        action="store_true",
        help="OCR statements that have no text layer (scans); needs tesseract",
    )
    extract.add_argument(
        "--include-failed",
        action="store_true",
        help="ship rows from statements that fail reconciliation (off by default)",
    )
    extract.set_defaults(func=cmd_extract)

    dump = sub.add_parser("dump", help="print layout text for a PDF, for deriving a profile")
    dump.add_argument("pdf")
    dump.add_argument("--page", type=int, help="only this page")
    dump.add_argument("--ruler", action="store_true", help="print a character-column ruler")
    dump.add_argument("--skip-blank", action="store_true", help="omit blank lines")
    dump.add_argument("--ocr", action="store_true", help="OCR the PDF instead of reading its text")
    dump.set_defaults(func=cmd_dump)

    learn = sub.add_parser(
        "learn", help="infer a draft profile for an unfamiliar statement"
    )
    learn.add_argument("pdf")
    learn.add_argument("--ocr", action="store_true", help="OCR the PDF first (scans)")
    learn.set_defaults(func=cmd_learn)

    profiles = sub.add_parser("profiles", help="list bank profiles")
    profiles.set_defaults(func=cmd_profiles)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (PopplerMissing, TesseractMissing) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
