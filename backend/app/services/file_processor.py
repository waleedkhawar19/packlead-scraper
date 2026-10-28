"""Extract emails and website URLs from uploaded documents.

Supported: .pdf .docx .xlsx .xls .csv .txt .md .html .htm .json .xml
Not supported: legacy .doc (no reliable local extractor - convert to .docx first).

Files are only ever *read as data*. They are never executed, stored under their original names, or
trusted for their declared type: extension, MIME type and magic bytes must all agree."""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.services.email_extractor import (
    extract_emails_from_text,
    extract_from_html,
    extract_urls_from_text,
    normalize_email,
)
from app.utils.security import safe_display_filename
from app.utils.url_safety import InvalidURLError, normalize_url

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt", ".md", ".html", ".htm", ".json", ".xml"}
TABULAR = {".xlsx", ".xls", ".csv"}

_OCTET = "application/octet-stream"
ALLOWED_MIME: Dict[str, set] = {
    ".pdf": {"application/pdf", "application/x-pdf", _OCTET},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip", _OCTET},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip", _OCTET},
    ".xls": {"application/vnd.ms-excel", "application/msexcel", _OCTET},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain", "application/x-csv", _OCTET},
    ".txt": {"text/plain", _OCTET},
    ".md": {"text/markdown", "text/x-markdown", "text/plain", _OCTET},
    ".html": {"text/html", "application/xhtml+xml", "text/plain", _OCTET},
    ".htm": {"text/html", "application/xhtml+xml", "text/plain", _OCTET},
    ".json": {"application/json", "text/json", "text/plain", _OCTET},
    ".xml": {"application/xml", "text/xml", "text/plain", _OCTET},
}


class UnsupportedFileError(Exception):
    """File type/size/MIME not accepted."""


class CorruptedFileError(Exception):
    """File matched a supported type but could not be parsed."""


# ----------------------------------------------------------------------------- data classes
@dataclass
class FileEmail:
    email: str
    original: str
    context: str = ""
    sheet: Optional[str] = None
    row: Optional[int] = None
    page: Optional[int] = None
    business_name: str = ""
    website: str = ""
    extra: Optional[Dict[str, Any]] = None


@dataclass
class FileUrl:
    url: str  # normalized
    original: str
    sheet: Optional[str] = None
    row: Optional[int] = None
    page: Optional[int] = None
    business_name: str = ""
    extra: Optional[Dict[str, Any]] = None


@dataclass
class ColumnInfo:
    index: int
    name: str
    sample: List[str]
    url_ratio: float
    email_ratio: float


@dataclass
class SheetInfo:
    name: str
    rows: int
    has_header: bool
    columns: List[ColumnInfo]
    suggested_url_columns: List[int]
    suggested_email_columns: List[int]
    suggested_name_column: Optional[int]


@dataclass
class FileExtraction:
    filename: str
    kind: str
    emails: List[FileEmail] = field(default_factory=list)
    urls: List[FileUrl] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    needs_ocr: bool = False
    pages: Optional[int] = None
    unique_emails: int = 0
    duplicate_emails: int = 0


# ----------------------------------------------------------------------------- validation
def validate_upload(filename: str, size: int, content_type: Optional[str], head: bytes) -> str:
    """Return the normalised extension or raise UnsupportedFileError."""
    settings = get_settings()
    name = safe_display_filename(filename)
    ext = Path(name).suffix.lower()
    if ext == ".doc":
        raise UnsupportedFileError(
            "Legacy .doc files cannot be read reliably. Open the file in Word/LibreOffice and save it as .docx, then upload again."
        )
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"'{ext or 'no extension'}' files are not supported. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    if size <= 0:
        raise UnsupportedFileError("The file is empty.")
    if size > settings.max_upload_bytes:
        raise UnsupportedFileError(f"File is larger than the {settings.max_upload_mb} MB limit.")
    if content_type:
        base = content_type.split(";")[0].strip().lower()
        if base not in ALLOWED_MIME[ext]:
            raise UnsupportedFileError(f"Content type '{base}' does not match a {ext} file.")
    _check_magic(ext, head)
    return ext


def _check_magic(ext: str, head: bytes) -> None:
    if ext == ".pdf" and not head.lstrip()[:5].startswith(b"%PDF-"):
        raise UnsupportedFileError("File content is not a PDF (missing %PDF header).")
    if ext in (".docx", ".xlsx") and not head.startswith(b"PK"):
        raise UnsupportedFileError(f"File content is not a valid {ext} (not a ZIP-based Office file).")
    if ext == ".xls" and not (head.startswith(b"\xd0\xcf\x11\xe0") or head.startswith(b"PK")):
        raise UnsupportedFileError("File content is not a valid .xls workbook.")
    if ext in (".csv", ".txt", ".md", ".html", ".htm", ".json", ".xml") and b"\x00" in head[:4096]:
        raise UnsupportedFileError("File looks binary, not text.")
    if head.startswith((b"MZ", b"\x7fELF")):
        raise UnsupportedFileError("Executable files are not accepted.")


def _check_zip_safe(path: Path) -> None:
    """Reject zip bombs / path-traversal members before handing Office files to a parser."""
    try:
        with zipfile.ZipFile(path) as zf:
            total = 0
            for info in zf.infolist():
                total += info.file_size
                if info.filename.startswith(("/", "..")) or ".." in Path(info.filename).parts:
                    raise CorruptedFileError("Archive contains unsafe paths.")
                if info.compress_size and info.file_size / max(info.compress_size, 1) > 200 and info.file_size > 10_000_000:
                    raise CorruptedFileError("Archive compression ratio is suspicious.")
            if total > 300 * 1024 * 1024:
                raise CorruptedFileError("File expands to more than 300 MB.")
    except zipfile.BadZipFile as exc:
        raise CorruptedFileError("File is corrupted or not a valid Office document.") from exc


# ----------------------------------------------------------------------------- generic helpers
def _read_text(path: Path) -> str:
    raw = path.read_bytes()[: get_settings().max_upload_bytes]
    for enc in ("utf-8-sig", "utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _emails_from(text: str, **loc: Any) -> List[FileEmail]:
    return [FileEmail(e.email, e.original, e.context, **loc) for e in extract_emails_from_text(text)]


def _urls_from(text: str, **loc: Any) -> List[FileUrl]:
    out: List[FileUrl] = []
    for u in extract_urls_from_text(text):
        try:
            out.append(FileUrl(normalize_url(u), u, **loc))
        except InvalidURLError:
            continue
    return out


def _finalize(res: FileExtraction) -> FileExtraction:
    """Deduplicate emails/URLs but keep every source reference on the first copy's siblings."""
    # Every occurrence is kept (the lead service merges them and records each source reference);
    # here we only count how many distinct addresses there are.
    distinct = {e.email for e in res.emails}
    res.unique_emails = len(distinct)
    res.duplicate_emails = len(res.emails) - len(distinct)
    seen_u: set = set()
    urls: List[FileUrl] = []
    for u in res.urls:
        if u.url not in seen_u:
            seen_u.add(u.url)
            urls.append(u)
    res.urls = urls
    return res


# ----------------------------------------------------------------------------- tabular
_URL_CELL_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?::\d+)?(?:[/?#]\S*)?$", re.I)
_EMAIL_CELL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_NAME_HEADERS = re.compile(r"^(company|business|organi[sz]ation|account|client|customer|name|company name|business name|brand)\b", re.I)
_URL_HEADERS = re.compile(r"(web ?site|url|link|domain|homepage|web ?address|site)", re.I)
_EMAIL_HEADERS = re.compile(r"e-?mail", re.I)


_LOCAL_URL_RE = re.compile(r"^https?://(?:localhost|\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?(?:[/?#]\S*)?$", re.I)


def looks_like_url_cell(value: str) -> bool:
    """Domains and http(s) URLs. IP/localhost hosts need an explicit scheme (they are accepted here and
    refused later by the SSRF guard unless they are a configured test fixture)."""
    v = (value or "").strip()
    if not v or "@" in v:
        return False
    return bool(_LOCAL_URL_RE.match(v)) or (bool(_URL_CELL_RE.match(v)) and not re.fullmatch(r"\d+(\.\d+)+", v))


def read_table(path: Path, ext: str, sheet: Optional[str] = None) -> Tuple[List[str], str, List[List[str]]]:
    """Return (sheet_names, chosen_sheet, rows-as-strings). Rows are capped for memory safety."""
    settings = get_settings()
    cap = settings.max_table_rows
    if ext == ".csv":
        text = _read_text(path)
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        csv.field_size_limit(1_000_000)
        rows: List[List[str]] = []
        for i, row in enumerate(csv.reader(io.StringIO(text), dialect)):
            if i >= cap:
                break
            rows.append([c.strip() for c in row])
        return ["CSV"], "CSV", rows
    if ext == ".xlsx":
        _check_zip_safe(path)
        from openpyxl import load_workbook

        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise CorruptedFileError(f"Could not open the Excel file: {type(exc).__name__}") from exc
        try:
            names = list(wb.sheetnames)
            chosen = sheet if sheet in names else names[0]
            rows = []
            for i, row in enumerate(wb[chosen].iter_rows(values_only=True)):
                if i >= cap:
                    break
                rows.append(["" if c is None else str(c).strip() for c in row])
        finally:
            wb.close()
        return names, chosen, rows
    if ext == ".xls":
        import xlrd

        try:
            book = xlrd.open_workbook(str(path), on_demand=True)
        except Exception as exc:  # noqa: BLE001
            raise CorruptedFileError(f"Could not open the .xls file: {type(exc).__name__}") from exc
        names = book.sheet_names()
        chosen = sheet if sheet in names else names[0]
        ws = book.sheet_by_name(chosen)
        rows = [["" if c is None else str(c).strip() for c in ws.row_values(r)] for r in range(min(ws.nrows, cap))]
        book.release_resources()
        return names, chosen, rows
    raise UnsupportedFileError("Not a spreadsheet")


def _analyze_sheet(name: str, rows: List[List[str]]) -> SheetInfo:
    width = max((len(r) for r in rows[:200]), default=0)
    sample_rows = rows[:200]
    first = rows[0] if rows else []
    has_header = bool(first) and not any(looks_like_url_cell(c) or _EMAIL_CELL_RE.match(c or "") for c in first)
    body = sample_rows[1:] if has_header else sample_rows
    cols: List[ColumnInfo] = []
    for i in range(width):
        values = [r[i] for r in body if i < len(r) and r[i]]
        total = max(len(values), 1)
        url_ratio = sum(looks_like_url_cell(v) for v in values) / total
        email_ratio = sum(bool(_EMAIL_CELL_RE.match(v)) for v in values) / total
        header = first[i] if has_header and i < len(first) and first[i] else f"Column {i + 1}"
        cols.append(ColumnInfo(i, header, values[:3], round(url_ratio, 2), round(email_ratio, 2)))
    url_cols = [c.index for c in cols if c.url_ratio >= 0.5]
    if not url_cols:  # header-name hint when values are too messy to score
        url_cols = [c.index for c in cols if _URL_HEADERS.search(c.name) and c.url_ratio >= 0.2]
    email_cols = [c.index for c in cols if c.email_ratio >= 0.5 or (_EMAIL_HEADERS.search(c.name) and c.email_ratio >= 0.2)]
    name_col = next((c.index for c in cols if has_header and _NAME_HEADERS.match(c.name) and c.url_ratio < 0.5 and c.email_ratio < 0.5), None)
    return SheetInfo(name, max(len(rows) - (1 if has_header else 0), 0), has_header, cols, url_cols, email_cols, name_col)


def inspect_tabular(path: Path, ext: str) -> List[SheetInfo]:
    names, _, _ = read_table(path, ext)
    infos: List[SheetInfo] = []
    for n in names[:20]:
        _, chosen, rows = read_table(path, ext, n)
        infos.append(_analyze_sheet(chosen, rows))
    return infos


def _extract_tabular(
    path: Path, ext: str, filename: str, sheet: Optional[str], url_columns: Optional[List[int]], name_column: Optional[int],
    sheets_to_read: Optional[List[str]] = None,
) -> FileExtraction:
    res = FileExtraction(filename=filename, kind="tabular")
    names, chosen, _ = read_table(path, ext, sheet)
    targets = [chosen] if (sheet or ext == ".csv") else (sheets_to_read or names[:20])
    for sheet_name in targets:
        _, _, rows = read_table(path, ext, sheet_name)
        info = _analyze_sheet(sheet_name, rows)
        ucols = url_columns if url_columns is not None else info.suggested_url_columns
        ncol = name_column if name_column is not None else info.suggested_name_column
        start = 1 if info.has_header else 0
        headers = rows[0] if info.has_header and rows else []
        for r_idx in range(start, len(rows)):
            row = rows[r_idx]
            if not any(row):
                continue
            row_no = r_idx + 1  # 1-based, as shown in Excel
            extra = {(headers[i] if i < len(headers) and headers[i] else f"Column {i + 1}"): v for i, v in enumerate(row) if v}
            extra_trim = dict(list(extra.items())[:25])
            biz = row[ncol] if ncol is not None and ncol < len(row) else ""
            row_urls: List[str] = []
            for ci in ucols:
                if ci < len(row) and looks_like_url_cell(row[ci]):
                    try:
                        u = normalize_url(row[ci])
                        row_urls.append(u)
                        res.urls.append(FileUrl(u, row[ci], sheet_name, row_no, None, biz, extra_trim))
                    except InvalidURLError:
                        res.warnings.append(f"{sheet_name} row {row_no}: '{row[ci][:60]}' is not a valid URL")
            for ci, cell in enumerate(row):
                if "@" not in cell:
                    continue
                for found in extract_emails_from_text(cell):
                    res.emails.append(
                        FileEmail(found.email, found.original, found.context, sheet_name, row_no, None, biz, row_urls[0] if row_urls else "", extra_trim)
                    )
            # URLs written inside free-text cells
            for ci, cell in enumerate(row):
                if ci in ucols or not cell:
                    continue
                res.urls.extend(FileUrl(u.url, u.original, sheet_name, row_no, None, biz, extra_trim) for u in _urls_from(cell))
    return _finalize(res)


# ----------------------------------------------------------------------------- per-format extractors
def _extract_pdf(path: Path, filename: str) -> FileExtraction:
    import pymupdf

    settings = get_settings()
    res = FileExtraction(filename=filename, kind="pdf")
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise CorruptedFileError("PDF is corrupted or encrypted and cannot be read.") from exc
    try:
        if doc.needs_pass:
            raise CorruptedFileError("PDF is password-protected.")
        res.pages = doc.page_count
        total_chars = 0
        limit = min(doc.page_count, settings.max_pdf_pages)
        if doc.page_count > limit:
            res.warnings.append(f"Only the first {limit} of {doc.page_count} pages were processed.")
        for i in range(limit):
            page = doc[i]
            text = page.get_text("text") or ""
            if len(text.strip()) < 20 and settings.enable_ocr:
                text = _try_ocr(page) or text
            total_chars += len(text.strip())
            res.emails.extend(_emails_from(text, page=i + 1))
            res.urls.extend(_urls_from(text, page=i + 1))
            for link in page.get_links():
                uri = link.get("uri") or ""
                if uri.lower().startswith("mailto:"):
                    n = normalize_email(uri)
                    for found in extract_emails_from_text(n):
                        res.emails.append(FileEmail(found.email, found.original, "PDF link", page=i + 1))
                elif uri.lower().startswith(("http://", "https://")):
                    res.urls.extend(_urls_from(uri, page=i + 1))
        if limit and total_chars < 20 * limit:
            res.needs_ocr = True
            res.warnings.append(
                "This PDF has little or no extractable text - it is probably scanned images. Install Tesseract OCR "
                "(see README) and re-upload, or run it through OCR first."
            )
    finally:
        doc.close()
    return _finalize(res)


def _try_ocr(page) -> str:  # noqa: ANN001
    """Optional local OCR through PyMuPDF + Tesseract; silently unavailable if not installed."""
    try:
        tp = page.get_textpage_ocr(flags=0, full=True)
        return page.get_text("text", textpage=tp) or ""
    except Exception:  # noqa: BLE001 - Tesseract missing/misconfigured
        return ""


def _extract_docx(path: Path, filename: str) -> FileExtraction:
    _check_zip_safe(path)
    import docx

    res = FileExtraction(filename=filename, kind="docx")
    try:
        document = docx.Document(str(path))
    except Exception as exc:  # noqa: BLE001
        raise CorruptedFileError("Word document is corrupted or not a valid .docx.") from exc
    chunks: List[str] = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            chunks.append(" | ".join(cell.text for cell in row.cells))
    for section in document.sections:
        for part in (section.header, section.footer):
            chunks.extend(p.text for p in part.paragraphs)
    text = "\n".join(chunks)[: get_settings().max_text_chars]
    for chunk in chunks:  # per paragraph/table row so repeated addresses are counted as occurrences
        res.emails.extend(_emails_from(chunk))
    res.urls.extend(_urls_from(text))
    for rel in document.part.rels.values():  # hyperlinks (display text may differ from target)
        if rel.reltype.endswith("/hyperlink") and rel.is_external:
            target = rel.target_ref
            if target.lower().startswith("mailto:"):
                for found in extract_emails_from_text(normalize_email(target)):
                    res.emails.append(FileEmail(found.email, found.original, "Word hyperlink"))
            elif target.lower().startswith(("http://", "https://")):
                res.urls.extend(_urls_from(target))
    return _finalize(res)


def _extract_html(path: Path, filename: str) -> FileExtraction:
    res = FileExtraction(filename=filename, kind="html")
    markup = _read_text(path)[: get_settings().max_text_chars]
    data = extract_from_html(markup)
    for e in data.emails:
        res.emails.append(FileEmail(e.email, e.original, e.context, business_name=data.business_name))
    for link, _ in data.links:
        res.urls.extend(_urls_from(link))
    res.urls.extend(_urls_from(data.text))
    return _finalize(res)


def _walk_json(node: Any, out: List[str], depth: int = 0) -> None:
    if depth > 50:
        return
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for k, v in node.items():
            out.append(str(k))
            _walk_json(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_json(v, out, depth + 1)


def _extract_json(path: Path, filename: str) -> FileExtraction:
    res = FileExtraction(filename=filename, kind="json")
    raw = _read_text(path)[: get_settings().max_text_chars]
    try:
        strings: List[str] = []
        _walk_json(json.loads(raw), strings)
        text = "\n".join(strings)
        for chunk in strings:
            res.emails.extend(_emails_from(chunk))
    except ValueError:
        res.warnings.append("File is not valid JSON; scanned as plain text instead.")
        text = raw
        for n, line in enumerate(raw.splitlines(), 1):
            res.emails.extend(_emails_from(line, row=n))
    res.urls.extend(_urls_from(text))
    return _finalize(res)


def _extract_plain(path: Path, filename: str, kind: str) -> FileExtraction:
    res = FileExtraction(filename=filename, kind=kind)
    text = _read_text(path)[: get_settings().max_text_chars]
    if kind == "xml":
        text = re.sub(r"<!\[CDATA\[|\]\]>", " ", text)  # no XML parsing => no entity-expansion attacks
    for n, line in enumerate(text.splitlines(), 1):  # "row" = line number for text-like files
        res.emails.extend(_emails_from(line, row=n))
    # A plain list of websites ("company1.com" per line)? Then take the lines in order and report the bad ones.
    lines = [(n, ln.strip()) for n, ln in enumerate(text.splitlines(), 1) if ln.strip()]
    url_lines = [(n, ln) for n, ln in lines if looks_like_url_cell(ln)]
    if kind in ("txt", "md") and lines and len(url_lines) / len(lines) >= 0.5:
        for n, ln in lines:
            if (n, ln) in url_lines:
                try:
                    res.urls.append(FileUrl(normalize_url(ln), ln, row=n))
                except InvalidURLError:
                    res.warnings.append(f"Line {n}: '{ln[:60]}' is not a valid URL")
            elif "@" not in ln:
                res.warnings.append(f"Line {n}: '{ln[:60]}' is not a valid URL")
    else:
        res.urls.extend(_urls_from(text))
    return _finalize(res)


# ----------------------------------------------------------------------------- public API
def extract_file(
    path: Path,
    original_name: str,
    *,
    sheet: Optional[str] = None,
    url_columns: Optional[List[int]] = None,
    name_column: Optional[int] = None,
) -> FileExtraction:
    """Dispatch on extension. Raises UnsupportedFileError / CorruptedFileError."""
    filename = safe_display_filename(original_name)
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"'{ext}' files are not supported.")
    try:
        if ext in TABULAR:
            return _extract_tabular(path, ext, filename, sheet, url_columns, name_column)
        if ext == ".pdf":
            return _extract_pdf(path, filename)
        if ext == ".docx":
            return _extract_docx(path, filename)
        if ext in (".html", ".htm"):
            return _extract_html(path, filename)
        if ext == ".json":
            return _extract_json(path, filename)
        return _extract_plain(path, filename, ext.lstrip("."))
    except (UnsupportedFileError, CorruptedFileError):
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure is reported as a corrupted file
        raise CorruptedFileError(f"Could not read this {ext} file ({type(exc).__name__}).") from exc


def file_kind(ext: str) -> str:
    return "tabular" if ext in TABULAR else ext.lstrip(".")
