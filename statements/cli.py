"""Command-line entry point.

    python -m statements.cli extract ./statements --account-label CUR1 -o ./out
    python -m statements.cli dump statement.pdf --page 2
    python -m statements.cli profiles
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .layout import PopplerMissing, load_pages
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


def cmd_extract(args: argparse.Namespace) -> int:
    profile = get_profile(args.profile)
    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        print("No PDFs found.", file=sys.stderr)
        return 1

    docs, checks = [], []
    for pdf in pdfs:
        doc = parse_statement(pdf, profile)
        check = reconcile(doc)
        docs.append(doc)
        checks.append(check)

    # The reconciliation report is the thing to read first, so print it first.
    print(f"\nReconciliation — {profile.bank} / {profile.description}\n")
    header = f"{'statement':<34}{'open':>11}{'in':>10}{'out':>11}{'close':>11}   check"
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
    for doc in docs:
        if doc.source_file in passed or args.include_failed:
            rows.extend(transaction_rows(doc, args.account_label))

    out_dir = Path(args.output)
    write_csv(out_dir / "transactions.csv", TRANSACTION_COLUMNS, rows)
    write_csv(
        out_dir / "reconciliation.csv",
        RECONCILIATION_COLUMNS,
        [reconciliation_row(c) for c in checks],
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
        "-p", "--profile", default=DEFAULT_PROFILE, help=f"bank profile (default: {DEFAULT_PROFILE})"
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
    dump.set_defaults(func=cmd_dump)

    profiles = sub.add_parser("profiles", help="list bank profiles")
    profiles.set_defaults(func=cmd_profiles)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PopplerMissing as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
