from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CrawlSettingsIn(BaseModel):
    max_pages: int = Field(10, ge=1, le=500, description="Pages to visit per website")
    max_depth: int = Field(2, ge=0, le=10)
    delay: float = Field(1.0, ge=0, le=60, description="Seconds between requests to the same host")
    concurrency: int = Field(3, ge=1, le=50, description="Websites crawled in parallel")
    follow_external: bool = False
    keywords: List[str] = Field(default_factory=list, max_length=20)
    keyword_filter: bool = False
    validate_mx: bool = True
    tags: str = Field("", max_length=200)


class WebsiteJobCreate(CrawlSettingsIn):
    name: Optional[str] = Field(None, max_length=200)
    urls: List[str] = Field(..., min_length=1)

    @field_validator("urls")
    @classmethod
    def _strip(cls, v: List[str]) -> List[str]:
        out = [u.strip() for u in v if isinstance(u, str) and u.strip()]
        if not out:
            raise ValueError("Provide at least one URL")
        return out


class DirectoryJobCreate(CrawlSettingsIn):
    name: Optional[str] = Field(None, max_length=200)
    urls: List[str] = Field(..., min_length=1, max_length=100)
    max_pages: int = Field(5, ge=1, le=500)
    delay: float = Field(1.5, ge=0, le=60)
    crawl_websites: bool = False
    max_sites: int = Field(25, ge=1, le=200)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    status: str
    params: Dict[str, Any]
    input_filename: Optional[str]
    is_test: bool
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    total_urls: int
    processed_urls: int
    successful_urls: int
    failed_urls: int
    skipped_urls: int
    pages_visited: int
    pages_skipped: int
    emails_found: int
    unique_leads: int
    duplicates_removed: int
    error: Optional[str]


class JobCreated(BaseModel):
    job: JobOut
    valid_urls: int
    invalid_urls: int
    duplicate_urls: int


class JobUrlOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    original_input: Optional[str]
    status: str
    pages_visited: int
    pages_skipped: int
    emails_found: int
    error: Optional[str]
    note: Optional[str]
    row_ref: Optional[str]
    finished_at: Optional[datetime]


class Page(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
