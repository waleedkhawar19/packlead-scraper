from __future__ import annotations

import asyncio
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.leads import apply_filters
from app.config import get_settings
from app.database import get_db
from app.models.job import Job, JobUrl
from app.models.lead import Lead, LeadSource
from app.models.misc import ExportRecord
from app.schemas.job import Page
from app.schemas.lead import LeadFilters
from app.schemas.misc import ExportOut, ExportRequest
from app.services import excel_exporter

router = APIRouter(prefix="/api/exports", tags=["exports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _out(rec: ExportRecord) -> ExportOut:
    out = ExportOut.model_validate(rec)
    out.download_url = f"/api/exports/{rec.id}/download"
    return out


@router.post("", response_model=ExportOut, status_code=201)
async def create_export(body: ExportRequest, db: Session = Depends(get_db)):
    """Build a real .xlsx file. scope: all | selected | filtered | job. format: leads | unique_emails | by_domain."""
    from sqlalchemy.orm import selectinload

    filters = body.filters or LeadFilters()
    filters = filters.model_copy(update={"include_test": body.include_test or filters.include_test})
    stmt = select(Lead).options(selectinload(Lead.sources))
    description = "All leads"
    jobs: List[Job] = []
    if body.scope == "selected":
        if not body.ids:
            raise HTTPException(400, "No leads were selected.")
        stmt = stmt.where(Lead.id.in_(body.ids))
        description = f"{len(body.ids)} selected leads"
    elif body.scope == "filtered":
        stmt = apply_filters(stmt, filters)
        description = "Filtered leads: " + (", ".join(f"{k}={v}" for k, v in filters.model_dump(exclude_none=True, exclude_defaults=True).items()) or "none")
    elif body.scope == "job":
        if not body.job_id:
            raise HTTPException(400, "job_id is required for a job export.")
        job = db.get(Job, body.job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        jobs = [job]
        in_job = select(LeadSource.lead_id).where(LeadSource.job_id == body.job_id)
        stmt = stmt.where(or_(Lead.job_id == body.job_id, Lead.id.in_(in_job)))
        description = f"Results of job #{job.id}: {job.name}"
    else:
        if not filters.include_test:
            stmt = stmt.where(Lead.is_test.is_(False))
    leads = db.scalars(stmt.order_by(Lead.collected_at.desc(), Lead.id.desc()).limit(100_000)).all()
    if not leads:
        raise HTTPException(400, "Nothing to export: no leads match this selection.")

    fstmt = select(JobUrl).where(JobUrl.status.in_(("failed", "skipped")))
    if body.scope == "job":
        fstmt = fstmt.where(JobUrl.job_id == body.job_id)
    failed = db.scalars(fstmt.order_by(JobUrl.id.desc()).limit(5000)).all()
    if not jobs:
        jobs = db.scalars(select(Job).order_by(Job.id.desc()).limit(20)).all()

    def build() -> bytes:
        wb = excel_exporter.build_workbook(leads, scope=body.format, failed_urls=failed, jobs=jobs, title="PackLead Scraper export", description=description)
        return excel_exporter.workbook_bytes(wb)

    try:
        data = await asyncio.to_thread(build)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Export failed while building the workbook: {type(exc).__name__}: {exc}")

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    suffix = {"leads": "leads", "unique_emails": "unique-emails", "by_domain": "emails-by-domain"}[body.format]
    filename = f"packlead_{suffix}_{stamp}.xlsx"
    directory = Path(get_settings().export_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{secrets.token_hex(8)}_{filename}"
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise HTTPException(500, f"Export failed: could not write the file ({exc.strerror}).")
    rec = ExportRecord(filename=filename, path=str(path), scope=f"{body.scope}/{body.format}", description=description, row_count=len(leads),
                       size_bytes=len(data), params=body.model_dump(mode="json", exclude_none=True))
    db.add(rec)
    db.commit()
    return _out(rec)


@router.get("", response_model=Page)
def list_exports(page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(ExportRecord)) or 0
    rows = db.scalars(select(ExportRecord).order_by(ExportRecord.id.desc()).offset((max(page, 1) - 1) * page_size).limit(page_size)).all()
    return Page(items=[_out(r) for r in rows], total=total, page=page, page_size=page_size)


def _safe_path(rec: ExportRecord) -> Path:
    base = Path(get_settings().export_dir).resolve()
    p = Path(rec.path).resolve()
    if base not in p.parents:  # never serve anything outside the exports directory
        raise HTTPException(404, "File not found")
    return p


@router.get("/{export_id}/download")
def download(export_id: int, db: Session = Depends(get_db)):
    rec = db.get(ExportRecord, export_id)
    if not rec:
        raise HTTPException(404, "Export not found")
    p = _safe_path(rec)
    if not p.exists():
        raise HTTPException(410, "The export file has been deleted from the server. Create the export again.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", rec.filename)
    return FileResponse(p, media_type=XLSX, filename=safe_name)


@router.delete("/{export_id}")
def delete_export(export_id: int, db: Session = Depends(get_db)):
    rec = db.get(ExportRecord, export_id)
    if not rec:
        raise HTTPException(404, "Export not found")
    try:
        _safe_path(rec).unlink(missing_ok=True)
    except HTTPException:
        pass
    db.delete(rec)
    db.commit()
    return {"deleted": True}
