from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.job import utcnow


class Lead(Base):
    """One unique email address (deduplicated) with the best-known business details.

    Fields that could not be reliably identified stay NULL/empty - nothing is invented."""

    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_domain", "email_domain"),
        Index("ix_leads_collected", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)  # normalized lowercase
    original_email: Mapped[str] = mapped_column(String(320))  # as displayed at the source
    email_domain: Mapped[str] = mapped_column(String(255))
    is_role_based: Mapped[bool] = mapped_column(Boolean, default=False)

    business_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True, index=True)
    website: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    contact_page_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    category_source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # auto | manual
    category_evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    state: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)
    country: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    source_type: Mapped[str] = mapped_column(String(30), index=True)  # website|directory|upload|manual
    source_filename: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    verification_status: Mapped[str] = mapped_column(String(30), default="Unverified", index=True)
    verification_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # comma separated
    context_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # page text used for classification

    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sources: Mapped[list["LeadSource"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", passive_deletes=True
    )


class LeadSource(Base):
    """Every place an email was seen. Deduplicating leads never discards this provenance."""

    __tablename__ = "lead_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    source_filename: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    row_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snippet: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    original_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # original spreadsheet row etc.
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="sources")
