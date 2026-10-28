from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.lead import LeadFilters


class ExportRequest(BaseModel):
    scope: str = Field("all", pattern="^(all|selected|filtered|job)$")
    format: str = Field("leads", pattern="^(leads|unique_emails|by_domain)$")
    ids: Optional[List[int]] = Field(None, max_length=50000)
    filters: Optional[LeadFilters] = None
    job_id: Optional[int] = None
    include_test: bool = False


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    scope: str
    description: Optional[str]
    row_count: int
    size_bytes: int
    created_at: datetime
    download_url: Optional[str] = None


class SettingsUpdate(BaseModel):
    default_max_pages: Optional[int] = Field(None, ge=1, le=500)
    default_max_depth: Optional[int] = Field(None, ge=0, le=10)
    default_delay_seconds: Optional[float] = Field(None, ge=0, le=60)
    default_concurrency: Optional[int] = Field(None, ge=1, le=50)
    default_validate_mx: Optional[bool] = None
    default_tags: Optional[str] = Field(None, max_length=200)
    category_keywords: Optional[Dict[str, List[str]]] = None
