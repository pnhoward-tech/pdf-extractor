"""The whole pipeline over real PDFs, from file on disk to reconciled CSV.

The sample statements are rendered from the same fixtures the unit tests use,
so they carry no real financial data — but they go through poppler, the layout
parser and the reconciler exactly as a bank's own PDF would.
"""

import csv
import io
import shutil
from pathlib import Path

import pytest

from statements import batch
from statements.report import TRANSACTION_COLUMNS, transaction_rows

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "statements"

pytestmark = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="poppler-utils not installed"
)


@pytest.fixture(scope="module")
def result():
    pdfs = sorted(SAMPLES.glob("*.pdf"))
    assert pdfs, "run scripts/make_samples.py first"
    return batch.run(pdfs, account_label="SAMPLE")


def test_every_sample_statement_reconciles(result):
    failures = {o.source_file: o.check.notes for o in result.failed}
    assert not failures, failures


def test_each_sample_is_matched_to_its_own_profile(result):
    matched = {o.source_file: o.profile.name for o in result.outcomes}
    assert matched == {
        "statement_uk_card.pdf": "hsbc-uk-card",
        "statement_uk_current.pdf": "hsbc-uk",
        "statement_us_checking.pdf": "hsbc-us",
    }
    assert not any(o.inferred for o in result.outcomes)


def test_nothing_is_left_unparsed(result):
    """A line inside a transaction table that produced no row is a bug."""
    stray = [
        (o.source_file, w)
        for o in result.outcomes
        for w in o.doc.warnings
        if "no type code" in w or "no amount" in w
    ]
    assert not stray, stray


def test_dates_survive_the_round_trip_through_a_pdf(result):
    for outcome in result.outcomes:
        for txn in outcome.doc.transactions:
            assert txn.txn_date, f"{outcome.source_file}: {txn.description}"
            assert txn.date_confidence == "certain"


def test_both_currencies_come_through(result):
    assert {o.doc.currency for o in result.outcomes} == {"GBP", "USD"}


def test_the_csv_is_well_formed_and_carries_its_provenance(result):
    rows = []
    for outcome, _ in result.transactions():
        rows.extend(transaction_rows(outcome.doc, "SAMPLE", outcome.profile))

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=TRANSACTION_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    parsed = list(csv.DictReader(io.StringIO(buffer.getvalue())))

    assert len(parsed) == len(rows) == 16
    assert {r["source_account"] for r in parsed} == {"SAMPLE"}
    assert all(r["bank"] for r in parsed)
    assert all(r["paid_out"] or r["paid_in"] for r in parsed)
