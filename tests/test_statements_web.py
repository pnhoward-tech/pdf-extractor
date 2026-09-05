"""The statement extractor's web API."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.statements_api import looks_like_pdf
from tests.bank.fixtures import card_statement, us_statement


@pytest.fixture
def client():
    return TestClient(app)


def upload(text: str, name: str = "stmt.pdf"):
    """A stub PDF; parsing is redirected to fixture text by the caller."""
    return (name, b"%PDF-1.4 stub", "application/pdf")


@pytest.fixture
def stub_batch(monkeypatch):
    """Run the real pipeline over fixture text rather than a real PDF."""
    from pathlib import Path

    from statements import batch
    from statements.parse import parse_statement
    from statements.profiles import get_profile

    texts: dict[str, tuple[str, str]] = {}

    def fake_choose(pdf, requested, ocr):
        profile_name = texts[Path(pdf).name][1]
        return get_profile(profile_name), f"matched {profile_name}", False

    def fake_parse(pdf, profile, **kwargs):
        return parse_statement(pdf, profile, text=texts[Path(pdf).name][0])

    monkeypatch.setattr(batch, "choose_profile", fake_choose)
    monkeypatch.setattr(batch, "parse_statement", fake_parse)
    return texts


def test_the_statement_extractor_is_the_front_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Statement Extractor" in response.text


def test_profiles_are_listed_with_their_bank(client):
    payload = client.get("/api/statements/profiles").json()
    names = {p["name"] for p in payload["profiles"]}
    assert {"hsbc-us", "hsbc-uk", "hsbc-uk-card", "whitaker-us"} <= names
    card = next(p for p in payload["profiles"] if p["name"] == "hsbc-uk-card")
    assert card["liability"] is True


@pytest.mark.parametrize(
    "head,expected",
    [
        (b"%PDF-1.7", True),
        # Real statements do arrive with whitespace before the header.
        (b"\n%PDF-1.6\n", True),
        (b"   \r\n%PDF-1.4", True),
        (b"not a pdf at all", False),
        (b"", False),
    ],
)
def test_pdf_detection_tolerates_a_header_that_is_not_at_byte_zero(head, expected):
    assert looks_like_pdf(head) is expected


def test_a_non_pdf_is_rejected(client):
    response = client.post(
        "/api/statements/extract", files=[("files", ("notes.txt", b"hello", "text/plain"))]
    )
    assert response.status_code == 415


def test_no_files_is_rejected(client):
    assert client.post("/api/statements/extract", files=[]).status_code in (400, 422)


def test_extract_reports_per_statement_and_offers_both_csvs(client, stub_batch):
    stub_batch["a.pdf"] = (us_statement(), "hsbc-us")
    stub_batch["b.pdf"] = (card_statement(), "hsbc-uk-card")

    response = client.post(
        "/api/statements/extract",
        files=[("files", upload(None, "a.pdf")), ("files", upload(None, "b.pdf"))],
        data={"account_label": "MIXED", "ocr": "false"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert {s["source_file"] for s in payload["statements"]} == {"a.pdf", "b.pdf"}
    assert all(s["ok"] for s in payload["statements"])
    assert payload["row_count"] == payload["shipped_count"] == 13
    assert payload["held_back"] == []

    card = next(s for s in payload["statements"] if s["source_file"] == "b.pdf")
    assert card["liability"] is True
    assert card["currency"] == "GBP"

    for which, expected in (("transactions", 13), ("reconciliation", 2)):
        download = client.get(f"/api/statements/download/{payload['job_id']}/{which}")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/csv")
        assert len(list(csv.DictReader(io.StringIO(download.text)))) == expected


def test_rows_carry_where_they_came_from(client, stub_batch):
    stub_batch["a.pdf"] = (us_statement(), "hsbc-us")
    payload = client.post(
        "/api/statements/extract",
        files=[("files", upload(None, "a.pdf"))],
        data={"account_label": "CUR1"},
    ).json()
    row = payload["rows"][0]
    assert row["source_account"] == "CUR1"
    assert row["bank"] == "HSBC Bank USA, N.A."
    assert row["currency"] == "USD"
    assert row["date_confidence"]


def test_an_unreconciled_statement_is_shown_but_withheld_from_the_download(client, stub_batch):
    """The rows come back so they can be inspected, and are marked; the CSV
    that gets loaded into a workbook does not contain them."""
    stub_batch["good.pdf"] = (us_statement(), "hsbc-us")
    stub_batch["bad.pdf"] = (us_statement().replace("$180.00", "$999.00"), "hsbc-us")

    payload = client.post(
        "/api/statements/extract",
        files=[("files", upload(None, "good.pdf")), ("files", upload(None, "bad.pdf"))],
    ).json()

    assert payload["held_back"] == ["bad.pdf"]
    assert payload["row_count"] > payload["shipped_count"]
    assert {r["_reconciled"] for r in payload["rows"]} == {"yes", "no"}

    shipped = client.get(f"/api/statements/download/{payload['job_id']}/transactions").text
    assert "bad.pdf" not in shipped
    assert "good.pdf" in shipped


def test_an_unknown_profile_is_a_clear_error(client):
    response = client.post(
        "/api/statements/extract",
        files=[("files", upload(None))],
        data={"profile": "nope"},
    )
    assert response.status_code == 400
    assert "unknown profile" in response.json()["detail"]


def test_an_expired_job_says_so(client):
    response = client.get("/api/statements/download/deadbeef/transactions")
    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


def test_an_unknown_download_name_is_refused(client, stub_batch):
    stub_batch["a.pdf"] = (us_statement(), "hsbc-us")
    payload = client.post(
        "/api/statements/extract", files=[("files", upload(None, "a.pdf"))]
    ).json()
    assert client.get(f"/api/statements/download/{payload['job_id']}/secrets").status_code == 404


def test_uploads_do_not_outlive_the_request(client, stub_batch, tmp_path, monkeypatch):
    """Statements are somebody's finances; nothing is left on disk."""
    import tempfile

    made: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        made.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", tracking_mkdtemp)
    stub_batch["a.pdf"] = (us_statement(), "hsbc-us")
    client.post("/api/statements/extract", files=[("files", upload(None, "a.pdf"))])

    from pathlib import Path

    assert made and not any(Path(p).exists() for p in made)
