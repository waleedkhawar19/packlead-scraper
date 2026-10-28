from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import Job, JobUrl
from app.models.lead import Lead, LeadSource
from app.schemas.job import JobOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def stats(include_test: bool = False, db: Session = Depends(get_db)):
    """Headline numbers. Sample/test data is excluded unless include_test=true."""
    lead_f = [] if include_test else [Lead.is_test.is_(False)]
    job_f = [] if include_test else [Job.is_test.is_(False)]

    unique_emails = db.scalar(select(func.count()).select_from(Lead).where(*lead_f)) or 0
    total_sightings = db.scalar(select(func.count()).select_from(LeadSource).join(Lead, Lead.id == LeadSource.lead_id).where(*lead_f)) or 0
    businesses = db.scalar(select(func.count(distinct(func.lower(Lead.business_name)))).where(Lead.business_name.is_not(None), Lead.business_name != "", *lead_f)) or 0
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min)
    today = db.scalar(select(func.count()).select_from(Lead).where(Lead.created_at >= today_start, *lead_f)) or 0

    def url_count(*conds):  # noqa: ANN002
        return db.scalar(select(func.count()).select_from(JobUrl).join(Job, Job.id == JobUrl.job_id).where(*job_f, *conds)) or 0

    processed = url_count(JobUrl.status != "pending")
    pending_jobs = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(("queued", "running", "paused")), *job_f)) or 0
    duplicates = db.scalar(select(func.coalesce(func.sum(Job.duplicates_removed), 0)).where(*job_f)) or 0
    categories = [{"name": n or "Uncategorised", "count": c} for n, c in db.execute(select(Lead.category, func.count()).where(*lead_f).group_by(Lead.category).order_by(func.count().desc()).limit(8))]
    recent = db.scalars(select(Job).where(*job_f).order_by(Job.id.desc()).limit(6)).all()
    return {
        "total_leads_collected": total_sightings, "unique_emails": unique_emails, "unique_businesses": businesses,
        "websites_processed": processed, "successful_crawls": url_count(JobUrl.status == "success"),
        "failed_websites": url_count(JobUrl.status == "failed"), "skipped_websites": url_count(JobUrl.status == "skipped"),
        "pending_jobs": pending_jobs, "leads_today": today, "duplicates_removed": int(duplicates), "categories": categories,
        "recent_jobs": [JobOut.model_validate(j) for j in recent], "includes_test_data": include_test,
    }
