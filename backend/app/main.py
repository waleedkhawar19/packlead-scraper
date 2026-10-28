"""FastAPI application entry point:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import dashboard, exports, jobs, leads, settings as settings_api, uploads
from app.config import get_settings
from app.database import engine, init_db
from app.logging_config import setup_logging
from app.workers.runner import JobRunner

log = logging.getLogger("packlead.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    s = get_settings()
    init_db()
    try:
        removed = uploads.purge_expired_uploads()
        if removed:
            log.info("purged %s expired upload files", removed)
    except OSError:
        log.exception("could not purge old uploads")
    runner = None
    task = None
    if s.embedded_worker:
        runner = JobRunner()
        task = asyncio.create_task(runner.run_forever())
    log.info("PackLead Scraper API ready (env=%s, db=%s, embedded_worker=%s)", s.environment, "sqlite" if s.is_sqlite else "postgresql", s.embedded_worker)
    yield
    if runner and task:
        runner.stop()
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()


app = FastAPI(title="PackLead Scraper API", version="1.0.0", lifespan=lifespan,
              description="Collect publicly listed business emails for lead research. No marketing emails are ever sent.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,  # explicit origins only - never "*" with credentials
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

for module in (jobs, leads, uploads, exports, dashboard, settings_api):
    app.include_router(module.router)


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
def health():
    """Liveness + database connectivity (used by hosting platforms)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return JSONResponse({"status": "ok" if db_ok else "degraded", "database": db_ok, "version": app.version}, status_code=200 if db_ok else 503)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Internal server error. Check the server log for details."}, status_code=500)
