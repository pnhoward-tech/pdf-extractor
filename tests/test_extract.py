from app.extract import clean_cell, extract_document


def test_extracts_ruled_table(invoice_pdf):
    doc = extract_document(invoice_pdf, "inv.pdf")
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert table.header == ["Item", "Qty", "Unit Price", "Line Total"]
    assert len(table.rows) == 3
    assert table.rows[0][0] == "Consulting services"
    assert table.page == 1


def test_page_text_is_captured(statement_pdf):
    doc = extract_document(statement_pdf, "stmt.pdf")
    assert "Statement of account" in doc.text


def test_all_rows_padded_to_header_width(statement_pdf):
    doc = extract_document(statement_pdf, "stmt.pdf")
    table = doc.tables[0]
    assert all(len(row) == table.width for row in table.rows)


def test_no_tables_produces_warning(textless_pdf):
    doc = extract_document(textless_pdf, "letter.pdf")
    assert doc.tables == []
    assert any("scan" in w for w in doc.warnings)


def test_clean_cell_collapses_wrapped_text():
    assert clean_cell("Consulting\nservices  Ltd") == "Consulting services Ltd"
    assert clean_cell(None) == ""
