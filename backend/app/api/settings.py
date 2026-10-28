from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas.misc import SettingsUpdate
from app.services import app_settings
from app.services.category_classifier import DEFAULT_CATEGORY_KEYWORDS

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _payload(db: Session) -> dict:
    s = get_settings()
    return {
        "settings": app_settings.get_all(db),
        "default_category_keywords": DEFAULT_CATEGORY_KEYWORDS,
        "server_limits": {
            "max_pages_limit": s.max_pages_limit, "max_depth_limit": s.max_depth_limit, "max_job_concurrency": s.max_job_concurrency,
            "global_concurrency": s.global_concurrency, "min_domain_delay": s.min_domain_delay, "max_urls_per_job": s.max_urls_per_job,
            "max_upload_mb": s.max_upload_mb, "request_timeout": s.request_timeout, "max_page_bytes": s.max_page_bytes,
            "respect_robots_txt": s.respect_robots_txt, "user_agent": s.user_agent, "environment": s.environment,
            "embedded_worker": s.embedded_worker, "database": "SQLite" if s.is_sqlite else "PostgreSQL", "ocr_enabled": s.enable_ocr,
            "test_fixture_hosts": sorted(s.fixture_host_set),
        },
    }


@router.get("")
def read_settings(db: Session = Depends(get_db)):
    return _payload(db)


@router.put("")
def write_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    app_settings.update(db, body.model_dump(exclude_unset=True))
    return _payload(db)
