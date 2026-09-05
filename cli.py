#!/usr/bin/env python3
"""Command-line front end. The web UI is the main interface; this is for scripting.

    python cli.py ./pdfs -o out.csv [--profile invoice] [--only-matched]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.mapping import load_profiles
from app.pipeline import process_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="*", help="PDF files, or directories of PDFs")
    parser.add_argument("-o", "--output", default="out.csv", help="CSV to write (default: out.csv)")
    parser.add_argument("-p", "--profile", default="auto", help="profile name, or 'auto'")
    parser.add_argument(
        "--only-matched",
        action="store_true",
        help="skip tables that no profile matched instead of emitting their raw headers",
    )
    parser.add_argument("--list-profiles", action="store_true", help="print profiles and exit")
    args = parser.parse_args(argv)

    if args.list_profiles:
        for profile in load_profiles():
            print(f"{profile.name:<12} {profile.description}")
        return 0

    paths: list[Path] = []
    for raw in args.inputs:
        path = Path(raw)
        paths.extend(sorted(path.glob("*.pdf")) if path.is_dir() else [path])
    if not paths:
        print("No PDFs found.", file=sys.stderr)
        return 1

    result = process_paths(
        paths,
        forced_profile_name=args.profile,
        include_unmatched=not args.only_matched,
    )
    Path(args.output).write_text(result.to_csv(), encoding="utf-8")

    for report in result.files:
        if report.error:
            print(f"  ! {report.filename}: {report.error}", file=sys.stderr)
            continue
        profiles_used = ", ".join(sorted({t.profile for t in report.tables})) or "none"
        print(f"  - {report.filename}: {report.row_count} rows [{profiles_used}]")
        for warning in report.warnings:
            print(f"    warning: {warning}", file=sys.stderr)

    print(f"\nWrote {result.row_count} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
