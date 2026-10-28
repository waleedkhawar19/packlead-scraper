"""Upload -> inspect -> preview -> commit. Files are stored under random names, never executed, and
deleted after commit (or on request / after a TTL)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas.upload import (
    ColumnOut, CommitRequest, PreviewEmail, PreviewOut, PreviewRequest, PreviewUrl, SheetOut, UploadOut,
)
from app.services import file_processor, job_manager
from app.services.file_processor import CorruptedFileError, FileExtraction, UnsupportedFileError
from app.utils.security import safe_display_filename

log = logging.getLogger("packlead.uploads")
router = APIRouter(prefix="/api/uploads", tags=["uploads"])
ID_RE = re.compile(r"^[0-9a-f]{32}$")
PREVIEW_LIMIT = 1000


def _dir() -> Path:
    d = Path(get_settings().upload_dir).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _paths(upload_id: str) -> tuple[Path, Path]:
    if not ID_RE.match(upload_id):  # blocks path traversal: ids are only ever 32 hex chars
        raise HTTPException(404, "Upload not found")
    base = _dir()
    meta = base / f"{upload_id}.json"
    if not meta.exists():
        raise HTTPException(404, "Upload not found (it may have expired). Please upload the file again.")
    info = json.loads(meta.read_text())
    return base / f"{upload_id}{info['extension']}", meta


def _load(upload_id: str) -> tuple[Path, dict]:
    path, meta = _paths(upload_id)
    if not path.exists():
        raise HTTPException(404, "Upload not found")
    return path, json.loads(meta.read_text())


def delete_upload_files(upload_id: str) -> None:
    base = _dir()
    for p in base.glob(f"{upload_id}*"):
        if p.is_file() and ID_RE.match(p.name.split(".")[0]):
            p.unlink(missing_ok=True)


def purge_expired_uploads() -> int:
    ttl = get_settings().upload_ttl_hours * 3600
    removed = 0
    for p in _dir().iterdir():
        if p.is_file() and ID_RE.match(p.name.split(".")[0]) and time.time() - p.stat().st_mtime > ttl:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


async def _run_extraction(path: Path, info: dict, req: PreviewRequest) -> FileExtraction:
    timeout = get_settings().file_processing_timeout
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(
        None,
        lambda: file_processor.extract_file(path, info["filename"], sheet=req.sheet, url_columns=req.url_columns, name_column=req.name_column),
    )
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(408, f"Processing took longer than {timeout:.0f}s and was stopped. Try a smaller file.")
    except UnsupportedFileError as exc:
        raise HTTPException(415, str(exc))
    except CorruptedFileError as exc:
        raise HTTPException(422, str(exc))


@router.post("", response_model=UploadOut, status_code=201)
async def upload_file(file: UploadFile = File(...)):
    """Store the file temporarily and (for spreadsheets) report sheets/columns so URL columns can be mapped."""
    settings = get_settings()
    display = safe_display_filename(file.filename)
    upload_id = uuid.uuid4().hex
    tmp = _dir() / f"{upload_id}.part"
    size = 0
    head = b""
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if not head:
                    head = chunk[:4096]
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise UnsupportedFileError(f"File is larger than the {settings.max_upload_mb} MB limit.")
                out.write(chunk)
        ext = file_processor.validate_upload(display, size, file.content_type, head)
        final = _dir() / f"{upload_id}{ext}"
        tmp.replace(final)
        (_dir() / f"{upload_id}.json").write_text(json.dumps({"filename": display, "extension": ext, "size": size, "created": time.time()}))
    except UnsupportedFileError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(415, str(exc))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    kind = file_processor.file_kind(ext)
    sheets: List[SheetOut] = []
    if kind == "tabular":
        try:
            infos = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, file_processor.inspect_tabular, final, ext), timeout=settings.file_processing_timeout)
            sheets = [SheetOut(**{**vars(s), "columns": [ColumnOut(**vars(c)) for c in s.columns]}) for s in infos]
        except (CorruptedFileError, UnsupportedFileError) as exc:
            delete_upload_files(upload_id)
            raise HTTPException(422, str(exc))
        except asyncio.TimeoutError:
            delete_upload_files(upload_id)
            raise HTTPException(408, "The spreadsheet took too long to analyse.")
    return UploadOut(upload_id=upload_id, filename=display, extension=ext, kind=kind, size_bytes=size, sheets=sheets)


def _group(extraction: FileExtraction) -> tuple[List[PreviewEmail], List[PreviewUrl]]:
    grouped: "OrderedDict[str, PreviewEmail]" = OrderedDict()
    for e in extraction.emails:
        item = grouped.get(e.email)
        src = {"filename": extraction.filename, "sheet": e.sheet, "row": e.row, "page": e.page, "context": e.context[:160]}
        if item is None:
            grouped[e.email] = PreviewEmail(email=e.email, original=e.original, occurrences=1, sources=[src], business_name=e.business_name, website=e.website)
        else:
            item.occurrences += 1
            if len(item.sources) < 5:
                item.sources.append(src)
    urls = [PreviewUrl(url=u.url, original=u.original, sheet=u.sheet, row=u.row, page=u.page, business_name=u.business_name) for u in extraction.urls]
    return list(grouped.values()), urls


@router.post("/{upload_id}/preview", response_model=PreviewOut)
async def preview(upload_id: str, body: PreviewRequest):
    """Run extraction without saving anything, so you can check the results before exporting."""
    path, info = _load(upload_id)
    extraction = await _run_extraction(path, info, body)
    emails, urls = _group(extraction)
    return PreviewOut(
        filename=extraction.filename, kind=extraction.kind, emails_total=len(extraction.emails), unique_emails=extraction.unique_emails,
        duplicate_emails=extraction.duplicate_emails, urls_total=len(urls), emails=emails[:PREVIEW_LIMIT], urls=urls[:PREVIEW_LIMIT],
        warnings=extraction.warnings[:20], needs_ocr=extraction.needs_ocr, pages=extraction.pages,
        truncated=len(emails) > PREVIEW_LIMIT or len(urls) > PREVIEW_LIMIT,
    )


@router.post("/{upload_id}/commit")
async def commit(upload_id: str, body: CommitRequest, db: Session = Depends(get_db)):
    """Save extracted emails as leads and/or queue a crawl of the websites found in the file."""
    if not body.save_emails and not body.crawl_urls:
        raise HTTPException(400, "Choose at least one action: save the emails and/or crawl the websites.")
    path, info = _load(upload_id)
    extraction = await _run_extraction(path, info, body)
    result: Dict[str, object] = {"filename": extraction.filename}
    tags = body.tags
    try:
        if body.save_emails:
            job, stats = job_manager.create_upload_job(db, filename=extraction.filename, extraction=extraction, tags=tags, name=body.name)
            result["extract_job"] = {"id": job.id, "created": stats.created, "duplicates": stats.duplicates, "rejected": stats.rejected}
        if body.crawl_urls:
            items = []
            for u in extraction.urls:
                extra = dict(u.extra or {})
                if u.business_name:
                    extra["_business_name"] = u.business_name
                items.append({"url": u.url, "row_ref": f"{u.sheet or ''}|{u.row}" if u.row else None, "extra": extra or None})
            params = body.model_dump(include={"max_pages", "max_depth", "delay", "concurrency", "follow_external", "keywords", "keyword_filter", "validate_mx", "tags"})
            job, counts = job_manager.create_crawl_job(
                db, name=(body.name or f"Crawl websites from {extraction.filename}")[:200], urls=items, params=params,
                job_type="upload_crawl", input_filename=extraction.filename, source_type="website",
            )
            result["crawl_job"] = {"id": job.id, **counts}
    except job_manager.JobError as exc:
        raise HTTPException(400, str(exc))
    if body.delete_after:
        delete_upload_files(upload_id)
        result["file_deleted"] = True
    return result


@router.delete("/{upload_id}")
def delete_upload(upload_id: str):
    _paths(upload_id)
    delete_upload_files(upload_id)
    return {"deleted": True}
