"""Application configuration. Every value can be overridden with an environment variable
or a ``backend/.env`` file (see ``.env.example``). No API keys are needed for core features."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    # --- Core -------------------------------------------------------------
    app_name: str = "PackLead Scraper"
    environment: str = "development"  # development | production
    log_level: str = "INFO"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'packlead.db').as_posix()}"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Storage ----------------------------------------------------------
    upload_dir: str = str(PROJECT_DIR / "uploads")
    export_dir: str = str(PROJECT_DIR / "exports")
    upload_ttl_hours: int = 24
    max_upload_mb: int = 25

    # --- Worker -----------------------------------------------------------
    embedded_worker: bool = True  # run the job worker inside the API process
    worker_poll_seconds: float = 1.0

    # --- Crawling safety --------------------------------------------------
    user_agent: str = "PackLeadBot/1.0 (+lead research tool; respects robots.txt)"
    robots_product_token: str = "PackLeadBot"
    respect_robots_txt: bool = True
    request_timeout: float = 15.0
    max_page_bytes: int = 2_000_000
    max_redirects: int = 5
    request_retries: int = 2
    retry_backoff_seconds: float = 1.0
    global_concurrency: int = 8  # max simultaneous HTTP requests across all jobs
    max_job_concurrency: int = 10  # hard cap for "websites processed in parallel"
    min_domain_delay: float = 0.5  # hard floor for delay between requests to the same host
    max_pages_limit: int = 100  # hard cap for pages per website
    max_depth_limit: int = 4
    max_urls_per_job: int = 5000
    max_robots_delay: float = 10.0

    # --- File processing --------------------------------------------------
    file_processing_timeout: float = 60.0
    max_pdf_pages: int = 500
    max_table_rows: int = 200_000
    max_text_chars: int = 5_000_000
    enable_ocr: bool = True  # only used if Tesseract is installed locally

    # --- Email validation -------------------------------------------------
    dns_timeout: float = 3.0

    # --- Local test fixtures ---------------------------------------------
    # Exact "host:port" values that are allowed even though they are private addresses,
    # so the bundled fixture site can be crawled locally. Leave empty in production.
    test_fixture_hosts: str = ""

    @field_validator("environment")
    @classmethod
    def _env(cls, v: str) -> str:
        return v.lower()

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def fixture_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.test_fixture_hosts.split(",") if h.strip()}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    Path(s.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(s.export_dir).mkdir(parents=True, exist_ok=True)
    return s
