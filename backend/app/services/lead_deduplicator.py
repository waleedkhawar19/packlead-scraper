"""Persist extracted emails as deduplicated leads, keeping every source reference.

Rules
* One Lead row per normalised (lowercase) email. A second sighting never creates a second lead; it adds a
  LeadSource row (provenance) and increments the duplicate counter.
* Existing values are never overwritten by later sightings - blank fields are only *filled in*.
* Nothing is invented: fields stay NULL when the source did not provide them."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import utcnow
from app.models.lead import Lead, LeadSource
from app.services import category_classifier
from app.services.email_validator import STATUS_SYNTAX_OK, check_syntax, is_placeholder, is_role_based


@dataclass
class LeadCandidate:
    email: str
    original_email: str = ""
    source_type: str = "website"
    business_name: str = ""
    website: str = ""
    contact_page_url: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    address: str = ""
    phone: str = ""
    category: str = ""  # only set when the source itself supplied one (e.g. directory category)
    source_url: str = ""
    source_filename: str = ""
    sheet_name: Optional[str] = None
    row_number: Optional[int] = None
    page_number: Optional[int] = None
    snippet: str = ""
    extra: Optional[Dict[str, Any]] = None
    context_text: str = ""
    notes: str = ""
    collected_at: Optional[datetime] = None


@dataclass
class UpsertStats:
    found: int = 0
    created: int = 0
    duplicates: int = 0
    rejected: int = 0
    lead_ids: List[int] = field(default_factory=list)


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def upsert_leads(
    db: Session,
    candidates: Sequence[LeadCandidate],
    *,
    job_id: Optional[int] = None,
    is_test: bool = False,
    extra_keywords: Optional[Dict[str, List[str]]] = None,
    auto_classify: bool = True,
    tags: str = "",
) -> UpsertStats:
    stats = UpsertStats()
    if not candidates:
        return stats
    emails = list({c.email.lower().strip() for c in candidates})
    existing: Dict[str, Lead] = {}
    for i in range(0, len(emails), 500):  # chunk to stay under SQLite's variable limit
        for lead in db.scalars(select(Lead).where(Lead.email.in_(emails[i : i + 500]))):
            existing[lead.email] = lead
    seen_source_keys: set = set()

    for c in candidates:
        email = c.email.lower().strip()
        stats.found += 1
        ok, _ = check_syntax(email)
        if not ok or is_placeholder(email):
            stats.rejected += 1
            continue
        collected = c.collected_at or utcnow()
        lead = existing.get(email)
        if lead is None:
            lead = Lead(
                email=email,
                original_email=(c.original_email or email)[:320],
                email_domain=email.split("@", 1)[1],
                is_role_based=is_role_based(email),
                business_name=(c.business_name or None),
                website=c.website or None,
                contact_page_url=c.contact_page_url or None,
                city=c.city or None,
                state=c.state or None,
                country=c.country or None,
                address=(c.address or None),
                phone=c.phone or None,
                category=c.category or None,
                category_source="source" if c.category else None,
                source_type=c.source_type,
                source_filename=c.source_filename or None,
                source_url=c.source_url or None,
                collected_at=collected,
                verification_status=STATUS_SYNTAX_OK,
                verification_detail="Syntax is valid. DNS was not checked; mailbox existence is not confirmed.",
                notes=c.notes or None,
                tags=tags or None,
                context_text=(c.context_text or None),
                job_id=job_id,
                is_test=is_test,
            )
            if auto_classify and not lead.category and c.context_text:
                guess = category_classifier.classify(c.context_text, extra_keywords)
                if guess:
                    lead.category = guess["category"]
                    lead.category_source = "auto"
                    lead.category_evidence = guess
            db.add(lead)
            db.flush()
            existing[email] = lead
            stats.created += 1
        else:
            stats.duplicates += 1
            for attr in ("business_name", "website", "contact_page_url", "city", "state", "country", "address", "phone", "context_text"):
                if _blank(getattr(lead, attr)) and not _blank(getattr(c, attr)):
                    setattr(lead, attr, getattr(c, attr))
            if auto_classify and lead.category_source in (None, "auto") and not lead.category and lead.context_text:
                guess = category_classifier.classify(lead.context_text, extra_keywords)
                if guess:
                    lead.category, lead.category_source, lead.category_evidence = guess["category"], "auto", guess
        if lead.id not in stats.lead_ids:
            stats.lead_ids.append(lead.id)

        key = (lead.id, c.source_url, c.source_filename, c.sheet_name, c.row_number, c.page_number)
        if key in seen_source_keys:
            continue
        seen_source_keys.add(key)
        already = db.scalar(
            select(LeadSource.id).where(
                LeadSource.lead_id == lead.id,
                LeadSource.source_url == (c.source_url or None),
                LeadSource.source_filename == (c.source_filename or None),
                LeadSource.sheet_name == c.sheet_name,
                LeadSource.row_number == c.row_number,
                LeadSource.page_number == c.page_number,
            ).limit(1)
        )
        if already:
            continue
        db.add(
            LeadSource(
                lead_id=lead.id,
                job_id=job_id,
                source_type=c.source_type,
                source_url=c.source_url or None,
                source_filename=c.source_filename or None,
                sheet_name=c.sheet_name,
                row_number=c.row_number,
                page_number=c.page_number,
                snippet=(c.snippet or "")[:400] or None,
                original_email=(c.original_email or None),
                extra=c.extra,
                collected_at=collected,
            )
        )
    db.flush()
    return stats
