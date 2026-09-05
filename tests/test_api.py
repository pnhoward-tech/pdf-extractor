import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_index_serves_the_ui(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "PDF Table Extractor" in response.text


def test_profiles_endpoint_lists_columns(client):
    payload = client.get("/api/profiles").json()
    invoice = next(p for p in payload["profiles"] if p["name"] == "invoice")
    assert "amount" in invoice["columns"]


def test_extract_then_download(client, invoice_pdf, statement_pdf):
    response = client.post(
        "/api/extract",
        files=[
            ("files", ("inv.pdf", invoice_pdf, "application/pdf")),
            ("files", ("stmt.pdf", statement_pdf, "application/pdf")),
        ],
        data={"profile": "auto", "include_unmatched": "true"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["row_count"] == 6
    assert not payload["truncated"]
    assert {f["filename"] for f in payload["files"]} == {"inv.pdf", "stmt.pdf"}

    download = client.get(f"/api/download/{payload['job_id']}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert len(list(csv.DictReader(io.StringIO(download.text)))) == 6


def test_non_pdf_upload_is_rejected(client):
    response = client.post(
        "/api/extract", files=[("files", ("notes.txt", b"hello", "text/plain"))]
    )
    assert response.status_code == 415


def test_unknown_profile_is_rejected(client, invoice_pdf):
    response = client.post(
        "/api/extract",
        files=[("files", ("inv.pdf", invoice_pdf, "application/pdf"))],
        data={"profile": "nope"},
    )
    assert response.status_code == 400


def test_expired_job_gives_a_clear_error(client):
    assert client.get("/api/download/deadbeef").status_code == 404
