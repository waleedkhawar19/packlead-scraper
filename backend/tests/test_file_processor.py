import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.file_processor import CorruptedFileError, UnsupportedFileError, extract_file, inspect_tabular, validate_upload


def make_pdf(path: Path, pages=("Contact: sales@acme-pack.com\nSee https://acme-pack.com/about",), link_mailto: str | None = None):
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        if link_mailto and page.number == 0:
            page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 100, 200, 120), "uri": f"mailto:{link_mailto}"})
    doc.save(str(path))
    doc.close()


def make_docx(path: Path):
    import docx

    d = docx.Document()
    d.add_paragraph("Reach our team at Hello@Acme-Pack.com or visit https://acme-pack.com")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Billing"
    t.cell(0, 1).text = "billing@acme-pack.com"
    d.sections[0].footer.paragraphs[0].text = "Footer: footer@acme-pack.com"
    d.save(str(path))


def test_pdf_emails_urls_and_page_numbers(tmp_path):
    p = tmp_path / "a.pdf"
    make_pdf(p, pages=("Page one: sales@acme-pack.com", "Page two: ops@acme-pack.com https://www.beta-pack.com"), link_mailto="link@acme-pack.com")
    res = extract_file(p, "a.pdf")
    by_email = {e.email: e.page for e in res.emails}
    assert by_email["sales@acme-pack.com"] == 1 and by_email["ops@acme-pack.com"] == 2
    assert by_email["link@acme-pack.com"] == 1  # hidden mailto: link target
    assert "https://www.beta-pack.com/" in [u.url for u in res.urls]
    assert res.pages == 2 and not res.needs_ocr


def test_scanned_pdf_is_flagged_for_ocr(tmp_path):
    import pymupdf

    p = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()  # no text layer at all
    doc.save(str(p))
    res = extract_file(p, "scan.pdf")
    assert res.needs_ocr and res.emails == [] and any("OCR" in w for w in res.warnings)


def test_corrupted_pdf_raises_clear_error(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"%PDF-1.7\nthis is not really a pdf")
    with pytest.raises(CorruptedFileError):
        extract_file(p, "bad.pdf")


def test_docx_paragraphs_tables_footer_and_hyperlinks(tmp_path):
    p = tmp_path / "a.docx"
    make_docx(p)
    res = extract_file(p, "a.docx")
    assert {e.email for e in res.emails} == {"hello@acme-pack.com", "billing@acme-pack.com", "footer@acme-pack.com"}
    assert "https://acme-pack.com/" in [u.url for u in res.urls]


def test_corrupted_docx_raises(tmp_path):
    p = tmp_path / "bad.docx"
    p.write_bytes(b"PK\x03\x04 definitely not a zip")
    with pytest.raises(CorruptedFileError):
        extract_file(p, "bad.docx")


def make_xlsx(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(["Company", "Website", "Contact", "Notes"])
    ws.append(["Acme Pack", "acme-pack.com", "buyer@acme-pack.com", "great"])
    ws.append(["Beta Boxes", "https://www.beta-boxes.com/contact", "", ""])
    ws.append(["Gamma", "not a url", "x@gamma.io", ""])
    ws2 = wb.create_sheet("Other")
    ws2.append(["Name", "Link", "Alt link"])
    ws2.append(["Delta", "delta.org", "https://delta-alt.net"])
    wb.save(path)


def test_xlsx_detects_url_and_email_columns_and_keeps_sheet_and_row(tmp_path):
    p = tmp_path / "leads.xlsx"
    make_xlsx(p)
    sheets = inspect_tabular(p, ".xlsx")
    leads = next(s for s in sheets if s.name == "Leads")
    assert leads.has_header and leads.suggested_url_columns == [1] and leads.suggested_email_columns == [2] and leads.suggested_name_column == 0
    res = extract_file(p, "leads.xlsx", sheet="Leads")
    assert [(u.url, u.sheet, u.row, u.business_name) for u in res.urls] == [
        ("https://acme-pack.com/", "Leads", 2, "Acme Pack"),
        ("https://www.beta-boxes.com/contact", "Leads", 3, "Beta Boxes"),
    ]
    assert any("not a url" in w for w in res.warnings) is False  # non-URL cells are simply not URLs
    e = {x.email: x for x in res.emails}
    assert e["buyer@acme-pack.com"].row == 2 and e["buyer@acme-pack.com"].business_name == "Acme Pack"
    assert e["buyer@acme-pack.com"].extra["Notes"] == "great"  # original columns are preserved


def test_xlsx_user_can_choose_url_columns_manually(tmp_path):
    p = tmp_path / "leads.xlsx"
    make_xlsx(p)
    res = extract_file(p, "leads.xlsx", sheet="Other", url_columns=[1, 2])
    assert {u.url for u in res.urls} == {"https://delta.org/", "https://delta-alt.net/"}


def test_csv_urls_and_semicolon_delimiter_and_cp1252(tmp_path):
    p = tmp_path / "sites.csv"
    p.write_bytes("Name;Site;Email\nCafé Pack;cafepack.com;hi@cafepack.com\nZed;zed.io;\n".encode("cp1252"))
    res = extract_file(p, "sites.csv")
    assert [u.url for u in res.urls] == ["https://cafepack.com/", "https://zed.io/"]
    assert res.emails[0].email == "hi@cafepack.com" and res.emails[0].business_name == "Café Pack"


def test_headerless_csv_of_urls(tmp_path):
    p = tmp_path / "urls.csv"
    p.write_text("company1.com\ncompany2.com\nhttps://example.org/contact\n")
    res = extract_file(p, "urls.csv")
    assert len(res.urls) == 3 and res.urls[2].url == "https://example.org/contact"


def test_website_list_text_file_import_normalizes_and_warns_on_malformed(tmp_path):  # noqa: E501
    p = tmp_path / "list.txt"
    p.write_text("company1.com\ncompany2.com\nhttps://example.org/contact\nhttps://example.net/about-us\nnot_a_url\n")
    res = extract_file(p, "list.txt")
    assert [u.url for u in res.urls] == ["https://company1.com/", "https://company2.com/", "https://example.org/contact", "https://example.net/about-us"]
    assert any("not_a_url" in w for w in res.warnings)


def test_html_json_xml_md_files(tmp_path):
    (tmp_path / "a.html").write_text('<html><body><a href="mailto:h@acme.com">x</a> <a href="https://acme.com/c">c</a></body></html>')
    (tmp_path / "a.json").write_text('{"contacts":[{"mail":"j@acme.com","site":"https://acme.com"}]}')
    (tmp_path / "bad.json").write_text('{"oops": "k@acme.com"')
    (tmp_path / "a.xml").write_text("<root><e>xml1@acme.com</e><![CDATA[xml2@acme.com]]></root>")
    (tmp_path / "a.md").write_text("# Notes\n* [mail us](mailto:m@acme.com) m@acme.com")
    assert {e.email for e in extract_file(tmp_path / "a.html", "a.html").emails} == {"h@acme.com"}
    assert {e.email for e in extract_file(tmp_path / "a.json", "a.json").emails} == {"j@acme.com"}
    bad = extract_file(tmp_path / "bad.json", "bad.json")
    assert {e.email for e in bad.emails} == {"k@acme.com"} and bad.warnings
    assert {e.email for e in extract_file(tmp_path / "a.xml", "a.xml").emails} == {"xml1@acme.com", "xml2@acme.com"}
    assert {e.email for e in extract_file(tmp_path / "a.md", "a.md").emails} == {"m@acme.com"}


def test_xml_entity_bombs_are_never_expanded(tmp_path):
    p = tmp_path / "bomb.xml"
    p.write_text('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><l>&b;&b;&b; ok@acme.com</l>')
    res = extract_file(p, "bomb.xml")
    assert [e.email for e in res.emails] == ["ok@acme.com"]


def test_empty_file_returns_no_results_not_an_error(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("nothing to see here")
    res = extract_file(p, "empty.txt")
    assert res.emails == [] and res.urls == []


# ------------------------------------------------------------------ upload validation
def test_validate_accepts_known_types():
    assert validate_upload("x.pdf", 100, "application/pdf", b"%PDF-1.4") == ".pdf"
    assert validate_upload("x.csv", 100, "application/vnd.ms-excel", b"a,b\n1,2") == ".csv"  # Windows sends this for CSV


@pytest.mark.parametrize(
    "name,size,ctype,head,needle",
    [
        ("x.doc", 100, None, b"\xd0\xcf\x11\xe0", "docx"),
        ("x.exe", 100, None, b"MZ", "not supported"),
        ("noext", 100, None, b"abc", "not supported"),
        ("x.pdf", 0, None, b"", "empty"),
        ("x.pdf", 10**9, None, b"%PDF-", "larger"),
        ("x.pdf", 100, "text/html", b"%PDF-", "does not match"),
        ("x.pdf", 100, None, b"<html>", "not a PDF"),
        ("x.docx", 100, None, b"%PDF-", "not a valid"),
        ("x.txt", 100, None, b"abc\x00def", "binary"),
        ("../../etc/passwd.sh", 100, None, b"#!/bin", "not supported"),
    ],
)
def test_validate_rejects_bad_uploads(name, size, ctype, head, needle):
    with pytest.raises(UnsupportedFileError) as exc:
        validate_upload(name, size, ctype, head)
    assert needle in str(exc.value)


def test_zip_bomb_like_office_file_is_rejected(tmp_path):
    p = tmp_path / "bomb.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(CorruptedFileError):
        extract_file(p, "bomb.docx")
