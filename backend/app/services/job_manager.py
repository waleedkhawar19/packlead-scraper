"""Job lifecycle + result persistence (synchronous SQLAlchemy; the async worker calls these through
``asyncio.to_thread``).

Status machine
    queued -> running -> completed | failed
    queued|running -> paused -> (resume) running/queued
    queued|running|paused -> cancelled
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.job import Job, JobUrl, utcnow
from app.models.lead import Lead
from app.services import app_settings
from app.services.directory_scraper import DirectoryResult
from app.services.file_processor import FileExtraction
from app.services.lead_deduplicator import LeadCandidate, UpsertStats, upsert_leads
from app.services.website_crawler import SiteResult
from app.utils.url_safety import InvalidURLError, normalize_url
from urllib.parse import urlsplit

ACTIVE = ("queued", "running", "paused")
FINAL = ("completed", "failed", "cancelled")


class JobError(Exception):
    pass


def clamp_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    s = get_settings()
    p = dict(raw)
    p["max_pages"] = max(1, min(int(p.get("max_pages", 10)), s.max_pages_limit))
    p["max_depth"] = max(0, min(int(p.get("max_depth", 2)), s.max_depth_limit))
    p["delay"] = max(s.min_domain_delay, min(float(p.get("delay", 1.0)), 30.0))
    p["concurrency"] = max(1, min(int(p.get("concurrency", 3)), s.max_job_concurrency))
    p["follow_external"] = bool(p.get("follow_external", False))
    p["keywords"] = [k.strip() for k in (p.get("keywords") or []) if isinstance(k, str) and k.strip()][:20]
    p["keyword_filter"] = bool(p.get("keyword_filter", False)) and bool(p["keywords"])
    p["validate_mx"] = bool(p.get("validate_mx", True))
    p["tags"] = (p.get("tags") or "")[:200]
    return p


def _is_fixture_url(url: str) -> bool:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{(parts.hostname or '').lower()}:{port}" in get_settings().fixture_host_set


def create_crawl_job(
    db: Session,
    *,
    name: str,
    urls: Sequence[Any],
    params: Dict[str, Any],
    job_type: str = "website",
    input_filename: Optional[str] = None,
    source_type: str = "website",
) -> Tuple[Job, Dict[str, int]]:
    """``urls`` items are either plain strings or dicts {url, row_ref, extra}. Returns (job, counts)."""
    s = get_settings()
    params = clamp_params(params)
    params["source_type"] = source_type
    if input_filename:
        params["source_filename"] = input_filename
    items: List[Dict[str, Any]] = [u if isinstance(u, dict) else {"url": u} for u in urls]
    if not items:
        raise JobError("No URLs were provided.")
    if len(items) > s.max_urls_per_job:
        raise JobError(f"Too many URLs ({len(items)}). The limit is {s.max_urls_per_job} per job.")
    job = Job(name=name[:200] or "Untitled job", type=job_type, status="queued", params=params, input_filename=input_filename)
    db.add(job)
    db.flush()
    seen: set = set()
    counts = {"valid": 0, "invalid": 0, "duplicates": 0}
    fixture_flags = []
    for it in items:
        raw = str(it["url"]).strip()
        try:
            norm = normalize_url(raw)
        except InvalidURLError as exc:
            db.add(JobUrl(job_id=job.id, url=raw[:2048], original_input=raw[:2048], status="failed", error=f"Invalid URL: {exc}",
                          row_ref=it.get("row_ref"), extra=it.get("extra"), finished_at=utcnow()))
            counts["invalid"] += 1
            continue
        key = norm.rstrip("/").lower()
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        fixture_flags.append(_is_fixture_url(norm))
        db.add(JobUrl(job_id=job.id, url=norm, original_input=raw[:2048], status="pending", row_ref=it.get("row_ref"), extra=it.get("extra")))
        counts["valid"] += 1
    job.total_urls = counts["valid"] + counts["invalid"]
    job.processed_urls = counts["invalid"]
    job.failed_urls = counts["invalid"]
    job.is_test = bool(fixture_flags) and all(fixture_flags)
    if counts["valid"] == 0:
        job.status, job.finished_at, job.started_at = "completed", utcnow(), utcnow()
    db.commit()
    db.refresh(job)
    return job, counts


def create_directory_job(db: Session, *, name: str, urls: Sequence[str], params: Dict[str, Any]) -> Tuple[Job, Dict[str, int]]:
    p = clamp_params(params)
    p["crawl_websites"] = bool(params.get("crawl_websites", False))
    p["max_sites"] = max(1, min(int(params.get("max_sites", 25)), 200))
    return create_crawl_job(db, name=name, urls=urls, params=p, job_type="directory", source_type="directory")


# ------------------------------------------------------------------ queries
def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise JobError("Job not found")
    return job


def set_status(db: Session, job_id: int, new_status: str, *, allowed_from: Iterable[str]) -> Job:
    job = get_job(db, job_id)
    if job.status not in allowed_from:
        raise JobError(f"Cannot change a '{job.status}' job to '{new_status}'.")
    if new_status == "paused":
        job.status = "paused"
    elif new_status == "resume":
        job.status = "running" if job.started_at else "queued"
    elif new_status == "cancelled":
        job.status = "cancelled"
        job.finished_at = utcnow()
    else:
        job.status = new_status
    db.commit()
    db.refresh(job)
    return job


def pause_job(db: Session, job_id: int) -> Job:
    return set_status(db, job_id, "paused", allowed_from=("queued", "running"))


def resume_job(db: Session, job_id: int) -> Job:
    return set_status(db, job_id, "resume", allowed_from=("paused",))


def cancel_job(db: Session, job_id: int) -> Job:
    return set_status(db, job_id, "cancelled", allowed_from=ACTIVE)


def delete_job(db: Session, job_id: int, delete_leads: bool = False) -> Dict[str, int]:
    job = get_job(db, job_id)
    if job.status in ("running",):
        raise JobError("Cancel the running job before deleting it.")
    removed = 0
    if delete_leads:
        ids = [i for (i,) in db.execute(select(Lead.id).where(Lead.job_id == job_id))]
        for i in range(0, len(ids), 500):
            db.execute(delete(Lead).where(Lead.id.in_(ids[i : i + 500])))
        removed = len(ids)
    db.delete(job)
    db.commit()
    return {"leads_deleted": removed}


def progress(db: Session, job: Job, recent: int = 15) -> Dict[str, Any]:
    pending = db.scalar(select(func.count()).select_from(JobUrl).where(JobUrl.job_id == job.id, JobUrl.status == "pending")) or 0
    recent_rows = db.scalars(
        select(JobUrl).where(JobUrl.job_id == job.id, JobUrl.status != "pending").order_by(JobUrl.finished_at.desc(), JobUrl.id.desc()).limit(recent)
    ).all()
    pct = 100.0 if job.status == "completed" else (job.processed_urls / job.total_urls * 100 if job.total_urls else 0.0)
    return {
        "job_id": job.id, "status": job.status, "percent": round(min(pct, 100.0), 1),
        "total_urls": job.total_urls, "processed_urls": job.processed_urls, "pending_urls": pending,
        "successful_urls": job.successful_urls, "failed_urls": job.failed_urls, "skipped_urls": job.skipped_urls,
        "pages_visited": job.pages_visited, "pages_skipped": job.pages_skipped, "emails_found": job.emails_found,
        "unique_leads": job.unique_leads, "duplicates_removed": job.duplicates_removed, "error": job.error,
        "started_at": job.started_at, "finished_at": job.finished_at,
        "recent": [
            {"id": r.id, "url": r.url, "status": r.status, "error": r.error, "note": r.note, "pages_visited": r.pages_visited,
             "pages_skipped": r.pages_skipped, "emails_found": r.emails_found}
            for r in recent_rows
        ],
    }


# ------------------------------------------------------------------ persistence of results
def _apply_counts(db: Session, job_id: int, ju: JobUrl, *, status: str, stats: UpsertStats, pages: int, pages_skipped: int, found: int) -> None:
    col = {"success": "successful_urls", "failed": "failed_urls", "skipped": "skipped_urls"}.get(status, "failed_urls")
    values = {
        "processed_urls": Job.processed_urls + 1,
        col: getattr(Job, col) + 1,
        "pages_visited": Job.pages_visited + pages,
        "pages_skipped": Job.pages_skipped + pages_skipped,
        "emails_found": Job.emails_found + found,
        "unique_leads": Job.unique_leads + stats.created,
        "duplicates_removed": Job.duplicates_removed + stats.duplicates,
    }
    db.execute(update(Job).where(Job.id == job_id).values(**values))


def persist_site_result(db: Session, job_id: int, jobu_id: int, res: SiteResult) -> UpsertStats:
    job = db.get(Job, job_id)
    ju = db.get(JobUrl, jobu_id)
    if job is None or ju is None:
        return UpsertStats()
    p = job.params or {}
    hint = (ju.extra or {}).get("_business_name") or ""
    sheet, row = _split_row_ref(ju.row_ref)
    note_bits = []
    if res.matched_keywords:
        note_bits.append("Matched keywords: " + ", ".join(res.matched_keywords))
    candidates = [
        LeadCandidate(
            email=e.email, original_email=e.original, source_type=p.get("source_type", "website"),
            business_name=hint or res.business_name, website=res.root_url, contact_page_url=res.contact_page_url,
            city=res.city, state=res.state, country=res.country, address=res.address, phone=res.phone,
            source_url=e.source_url, source_filename=p.get("source_filename", "") or "", sheet_name=sheet, row_number=row,
            snippet=e.context, extra={k: v for k, v in (ju.extra or {}).items() if not k.startswith("_")} or None,
            context_text=res.context_text, notes="; ".join(note_bits), collected_at=e.collected_at,
        )
        for e in res.emails
    ]
    stats = upsert_leads(db, candidates, job_id=job_id, is_test=job.is_test, extra_keywords=app_settings.custom_keywords(db), tags=p.get("tags", ""))
    ju.status = res.status if res.status in ("success", "failed", "skipped") else "failed"
    ju.pages_visited, ju.pages_skipped, ju.emails_found = res.pages_visited, res.pages_skipped, len(res.emails)
    ju.error = res.error
    ju.note = (res.note or "")[:1000] or None
    ju.finished_at = utcnow()
    _apply_counts(db, job_id, ju, status=ju.status, stats=stats, pages=res.pages_visited, pages_skipped=res.pages_skipped, found=len(res.emails))
    db.commit()
    return stats


def persist_directory_result(db: Session, job_id: int, jobu_id: int, res: DirectoryResult, site_results: Sequence[Tuple[Any, SiteResult]] = ()) -> UpsertStats:
    job = db.get(Job, job_id)
    ju = db.get(JobUrl, jobu_id)
    if job is None or ju is None:
        return UpsertStats()
    p = job.params or {}
    candidates: List[LeadCandidate] = []
    without_email = 0
    for rec in res.records:
        if not rec.emails:
            without_email += 1
        for em in rec.emails:
            candidates.append(
                LeadCandidate(
                    email=em, original_email=rec.original_emails.get(em, em), source_type="directory", business_name=rec.business_name,
                    website=rec.website, city=rec.city, state=rec.state, country=rec.country, address=rec.address, phone=rec.phone,
                    category=rec.category, source_url=rec.source_url, collected_at=rec.collected_at,
                    snippet=f"Listed in directory: {res.start_url}"[:400],
                )
            )
    for rec, site in site_results:
        for e in site.emails:
            candidates.append(
                LeadCandidate(
                    email=e.email, original_email=e.original, source_type="directory", business_name=rec.business_name or site.business_name,
                    website=site.root_url or rec.website, contact_page_url=site.contact_page_url, city=rec.city or site.city,
                    state=rec.state or site.state, country=rec.country or site.country, address=rec.address or site.address,
                    phone=rec.phone or site.phone, category=rec.category, source_url=e.source_url, snippet=e.context,
                    context_text=site.context_text, notes=f"Found on the business website listed in directory {res.start_url}", collected_at=e.collected_at,
                )
            )
    stats = upsert_leads(db, candidates, job_id=job_id, is_test=job.is_test, extra_keywords=app_settings.custom_keywords(db), tags=p.get("tags", ""))
    ju.status = res.status
    ju.pages_visited, ju.pages_skipped, ju.emails_found = res.pages_visited, res.pages_skipped, len(candidates)
    ju.error = res.error
    bits = [f"Adapter: {res.adapter}" if res.adapter else "", f"{len(res.records)} businesses parsed", f"{without_email} without a public email" if without_email else "", res.note]
    ju.note = "; ".join(b for b in bits if b)[:1000] or None
    ju.finished_at = utcnow()
    _apply_counts(db, job_id, ju, status=ju.status, stats=stats, pages=res.pages_visited, pages_skipped=res.pages_skipped, found=len(candidates))
    db.commit()
    return stats


def create_upload_job(
    db: Session, *, filename: str, extraction: FileExtraction, tags: str = "", name: Optional[str] = None
) -> Tuple[Job, UpsertStats]:
    """Persist emails found in an uploaded file as a completed 'upload' job."""
    job = Job(
        name=(name or f"Extract: {filename}")[:200], type="upload", status="running", input_filename=filename,
        params={"source_type": "upload", "source_filename": filename, "kind": extraction.kind, "tags": tags},
        started_at=utcnow(), total_urls=1,
    )
    db.add(job)
    db.flush()
    candidates = [
        LeadCandidate(
            email=e.email, original_email=e.original, source_type="upload", business_name=e.business_name, website=e.website,
            source_filename=filename, sheet_name=e.sheet, row_number=e.row, page_number=e.page, snippet=e.context, extra=e.extra,
            context_text="", collected_at=utcnow(),
        )
        for e in extraction.emails
    ]
    stats = upsert_leads(db, candidates, job_id=job.id, is_test=False, extra_keywords=None, auto_classify=False, tags=tags)
    job.processed_urls, job.successful_urls = 1, 1
    job.emails_found, job.unique_leads, job.duplicates_removed = len(candidates), stats.created, stats.duplicates
    job.status, job.finished_at = "completed", utcnow()
    job.params = {**job.params, "rejected_as_invalid_or_placeholder": stats.rejected}
    db.commit()
    db.refresh(job)
    return job, stats


def _split_row_ref(ref: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    if not ref or "|" not in ref:
        return None, None
    sheet, _, row = ref.rpartition("|")
    return (sheet or None), (int(row) if row.isdigit() else None)
