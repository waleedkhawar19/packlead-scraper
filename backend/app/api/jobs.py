from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import Job, JobUrl
from app.schemas.job import DirectoryJobCreate, JobCreated, JobOut, JobUrlOut, Page, WebsiteJobCreate
from app.services import job_manager
from app.services.job_manager import JobError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _err(exc: JobError) -> HTTPException:
    code = 404 if "not found" in str(exc).lower() else 400
    return HTTPException(status_code=code, detail=str(exc))


@router.post("/website", response_model=JobCreated, status_code=201)
def create_website_job(body: WebsiteJobCreate, db: Session = Depends(get_db)):
    """Queue a crawl for one or many website URLs (bare domains are fine)."""
    params = body.model_dump(exclude={"name", "urls"})
    name = body.name or (f"Website scrape: {body.urls[0]}" if len(body.urls) == 1 else f"Website scrape: {len(body.urls)} URLs")
    try:
        job, counts = job_manager.create_crawl_job(db, name=name, urls=body.urls, params=params, job_type="website" if len(body.urls) < 20 else "url_list")
    except JobError as exc:
        raise _err(exc)
    return JobCreated(job=job, valid_urls=counts["valid"], invalid_urls=counts["invalid"], duplicate_urls=counts["duplicates"])


@router.post("/directory", response_model=JobCreated, status_code=201)
def create_directory_job(body: DirectoryJobCreate, db: Session = Depends(get_db)):
    """Queue a public-directory scrape (respects robots.txt; skips login/CAPTCHA/blocked directories)."""
    params = body.model_dump(exclude={"name", "urls"})
    name = body.name or f"Directory scrape: {body.urls[0]}" + (f" (+{len(body.urls) - 1})" if len(body.urls) > 1 else "")
    try:
        job, counts = job_manager.create_directory_job(db, name=name, urls=body.urls, params=params)
    except JobError as exc:
        raise _err(exc)
    return JobCreated(job=job, valid_urls=counts["valid"], invalid_urls=counts["invalid"], duplicate_urls=counts["duplicates"])


@router.get("", response_model=Page)
def list_jobs(
    status: Optional[str] = None,
    type: Optional[str] = None,
    include_test: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    if type:
        stmt = stmt.where(Job.type == type)
    if not include_test:
        stmt = stmt.where(Job.is_test.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Job.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[JobOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    try:
        return job_manager.get_job(db, job_id)
    except JobError as exc:
        raise _err(exc)


@router.get("/{job_id}/progress")
def job_progress(job_id: int, db: Session = Depends(get_db)):
    """Poll this every 1-2 seconds for live progress."""
    try:
        return job_manager.progress(db, job_manager.get_job(db, job_id))
    except JobError as exc:
        raise _err(exc)


@router.get("/{job_id}/urls", response_model=Page)
def job_urls(job_id: int, status: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    try:
        job_manager.get_job(db, job_id)
    except JobError as exc:
        raise _err(exc)
    stmt = select(JobUrl).where(JobUrl.job_id == job_id)
    if status:
        stmt = stmt.where(JobUrl.status.in_(status.split(",")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(JobUrl.id).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[JobUrlOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("/{job_id}/pause", response_model=JobOut)
def pause(job_id: int, db: Session = Depends(get_db)):
    try:
        return job_manager.pause_job(db, job_id)
    except JobError as exc:
        raise _err(exc)


@router.post("/{job_id}/resume", response_model=JobOut)
def resume(job_id: int, db: Session = Depends(get_db)):
    try:
        return job_manager.resume_job(db, job_id)
    except JobError as exc:
        raise _err(exc)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: int, db: Session = Depends(get_db)):
    try:
        return job_manager.cancel_job(db, job_id)
    except JobError as exc:
        raise _err(exc)


@router.delete("/{job_id}")
def delete(job_id: int, delete_leads: bool = False, db: Session = Depends(get_db)):
    """Delete a job and its per-URL records. Leads are kept unless ``delete_leads=true``."""
    try:
        return job_manager.delete_job(db, job_id, delete_leads)
    except JobError as exc:
        raise _err(exc)
