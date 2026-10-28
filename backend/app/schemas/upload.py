from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.job import CrawlSettingsIn


class ColumnOut(BaseModel):
    index: int
    name: str
    sample: List[str]
    url_ratio: float
    email_ratio: float


class SheetOut(BaseModel):
    name: str
    rows: int
    has_header: bool
    columns: List[ColumnOut]
    suggested_url_columns: List[int]
    suggested_email_columns: List[int]
    suggested_name_column: Optional[int]


class UploadOut(BaseModel):
    upload_id: str
    filename: str
    extension: str
    kind: str
    size_bytes: int
    sheets: List[SheetOut] = []


class PreviewRequest(BaseModel):
    sheet: Optional[str] = None
    url_columns: Optional[List[int]] = None
    name_column: Optional[int] = None


class PreviewEmail(BaseModel):
    email: str
    original: str
    occurrences: int
    sources: List[Dict[str, Any]]
    business_name: str = ""
    website: str = ""


class PreviewUrl(BaseModel):
    url: str
    original: str
    sheet: Optional[str] = None
    row: Optional[int] = None
    page: Optional[int] = None
    business_name: str = ""


class PreviewOut(BaseModel):
    filename: str
    kind: str
    emails_total: int
    unique_emails: int
    duplicate_emails: int
    urls_total: int
    emails: List[PreviewEmail]
    urls: List[PreviewUrl]
    warnings: List[str]
    needs_ocr: bool
    pages: Optional[int] = None
    truncated: bool = False


class CommitRequest(PreviewRequest, CrawlSettingsIn):
    save_emails: bool = True
    crawl_urls: bool = False
    delete_after: bool = True
    name: Optional[str] = Field(None, max_length=200)
