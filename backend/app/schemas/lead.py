from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.email_extractor import normalize_email


class LeadSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: Optional[str]
    source_url: Optional[str]
    source_filename: Optional[str]
    sheet_name: Optional[str]
    row_number: Optional[int]
    page_number: Optional[int]
    snippet: Optional[str]
    extra: Optional[Dict[str, Any]]
    collected_at: datetime


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    original_email: str
    email_domain: str
    is_role_based: bool
    business_name: Optional[str]
    website: Optional[str]
    contact_page_url: Optional[str]
    category: Optional[str]
    category_source: Optional[str]
    category_evidence: Optional[Dict[str, Any]]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    source_type: str
    source_filename: Optional[str]
    source_url: Optional[str]
    collected_at: datetime
    verification_status: str
    verification_detail: Optional[str]
    notes: Optional[str]
    tags: Optional[str]
    job_id: Optional[int]
    is_test: bool
    matched_keywords: Optional[List[str]] = None


class LeadDetail(LeadOut):
    sources: List[LeadSourceOut] = []


class LeadUpdate(BaseModel):
    business_name: Optional[str] = Field(None, max_length=300)
    website: Optional[str] = Field(None, max_length=2048)
    contact_page_url: Optional[str] = Field(None, max_length=2048)
    category: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=120)
    state: Optional[str] = Field(None, max_length=60)
    country: Optional[str] = Field(None, max_length=80)
    address: Optional[str] = Field(None, max_length=400)
    phone: Optional[str] = Field(None, max_length=60)
    notes: Optional[str] = Field(None, max_length=5000)
    tags: Optional[str] = Field(None, max_length=500)
    verification_status: Optional[str] = Field(None, max_length=30)


class LeadCreate(LeadUpdate):
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class BulkIds(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=20000)


class BulkTag(BulkIds):
    tags: List[str] = Field(..., min_length=1, max_length=20)
    mode: str = Field("add", pattern="^(add|remove|set)$")


class LeadFilters(BaseModel):
    """Shared by the leads list, bulk actions and Excel export ('filtered' scope)."""

    q: Optional[str] = None
    category: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    domain: Optional[str] = None
    source_type: Optional[str] = None
    verification_status: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    has_website: Optional[bool] = None
    role_based: Optional[bool] = None
    tag: Optional[str] = None
    job_id: Optional[int] = None
    keywords: Optional[str] = None  # comma separated prospect-search terms
    keyword_mode: str = "any"
    include_test: bool = False
    only_test: bool = False


class ValidateRequest(BaseModel):
    ids: Optional[List[int]] = None
    only_unverified: bool = True
    check_mx: bool = True


class ClassifyRequest(BaseModel):
    ids: Optional[List[int]] = None
