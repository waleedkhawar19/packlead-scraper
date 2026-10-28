from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # website | url_list | directory | upload | upload_crawl
    type: Mapped[str] = mapped_column(String(30), index=True)
    # queued | running | paused | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    input_filename: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    total_urls: Mapped[int] = mapped_column(Integer, default=0)
    processed_urls: Mapped[int] = mapped_column(Integer, default=0)
    successful_urls: Mapped[int] = mapped_column(Integer, default=0)
    failed_urls: Mapped[int] = mapped_column(Integer, default=0)
    skipped_urls: Mapped[int] = mapped_column(Integer, default=0)
    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    pages_skipped: Mapped[int] = mapped_column(Integer, default=0)
    emails_found: Mapped[int] = mapped_column(Integer, default=0)  # raw occurrences found
    unique_leads: Mapped[int] = mapped_column(Integer, default=0)  # new leads created
    duplicates_removed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    urls: Mapped[list["JobUrl"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class JobUrl(Base):
    """One input URL of a job and its outcome (this is how failed/skipped URLs are reported)."""

    __tablename__ = "job_urls"
    __table_args__ = (Index("ix_job_urls_job_status", "job_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    original_input: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    # pending | success | failed | skipped
    status: Mapped[str] = mapped_column(String(20), default="pending")
    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    pages_skipped: Mapped[int] = mapped_column(Integer, default=0)
    emails_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    row_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # e.g. "Sheet1|12"
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # original spreadsheet row, name hint
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    job: Mapped[Job] = relationship(back_populates="urls")
