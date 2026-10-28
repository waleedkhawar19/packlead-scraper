"""Background job runner. The *database* is the queue, so jobs survive restarts and the same code runs
embedded in the API process (default) or as a separate ``python -m app.workers.run_worker`` process.

* ``run_forever`` polls for the oldest queued job and runs it.
* Pause / resume / cancel are database status changes that the running job notices within ~1 s.
* On start-up, jobs left in 'running' (crashed/restarted server) go back to 'queued'; URLs that were
  already finished are not repeated."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select, update

from app.config import Settings, get_settings
from app.database import SessionLocal, session_scope
from app.models.job import Job, JobUrl, utcnow
from app.models.lead import Lead
from app.services import job_manager
from app.services.directory_scraper import DirectoryOptions, DirectoryScraper
from app.services.email_validator import STATUS_SYNTAX_OK, STATUS_UNVERIFIED, EmailValidator, MXLookup
from app.services.website_crawler import CrawlOptions, SiteResult, WebsiteCrawler
from app.utils.http import RateLimiter, SafeFetcher
from app.utils.url_safety import Resolver

log = logging.getLogger("packlead.worker")
SITE_TIMEOUT_SECONDS = 300


class JobControl:
    """Tiny cache of a job's DB status, refreshed in the background so crawlers can poll it cheaply."""

    def __init__(self, job_id: int):
        self.job_id = job_id
        self.status = "running"
        self._task: Optional[asyncio.Task] = None

    @property
    def cancelled(self) -> bool:
        return self.status in ("cancelled", "failed")

    async def refresh(self) -> None:
        def read() -> Optional[str]:
            with SessionLocal() as db:
                return db.scalar(select(Job.status).where(Job.id == self.job_id))

        self.status = (await asyncio.to_thread(read)) or "cancelled"

    def start(self) -> None:
        async def loop() -> None:
            while True:
                try:
                    await self.refresh()
                except Exception:  # noqa: BLE001
                    log.exception("status refresh failed")
                await asyncio.sleep(0.7)

        self._task = asyncio.create_task(loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def wait_if_paused(self) -> None:
        while self.status == "paused":
            await asyncio.sleep(0.5)


class JobRunner:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        resolver: Optional[Resolver] = None,
        mx_lookup: Optional[MXLookup] = None,
    ):
        self.settings = settings or get_settings()
        self.transport = transport
        self.resolver = resolver
        self.mx_lookup = mx_lookup
        self._limiter: Optional[RateLimiter] = None
        self._persist_lock: Optional[asyncio.Lock] = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ lifecycle
    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        await asyncio.to_thread(self.requeue_interrupted)
        log.info("job worker started")
        while not self._stop.is_set():
            try:
                ran = await self.run_next()
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")
                ran = False
            if not ran:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.worker_poll_seconds)
                except asyncio.TimeoutError:
                    pass
        log.info("job worker stopped")

    @staticmethod
    def requeue_interrupted() -> int:
        with session_scope() as db:
            res = db.execute(update(Job).where(Job.status == "running").values(status="queued"))
            return res.rowcount or 0

    @staticmethod
    def _claim() -> Optional[int]:
        with session_scope() as db:
            job = db.scalars(select(Job).where(Job.status == "queued").order_by(Job.id).limit(1)).first()
            if job is None:
                return None
            res = db.execute(update(Job).where(Job.id == job.id, Job.status == "queued").values(status="running", started_at=job.started_at or utcnow()))
            return job.id if res.rowcount else None

    async def run_next(self) -> bool:
        """Claim and run one queued job. Returns False if the queue was empty."""
        job_id = await asyncio.to_thread(self._claim)
        if job_id is None:
            return False
        await self.run_job(job_id)
        return True

    # ------------------------------------------------------------------ one job
    async def run_job(self, job_id: int) -> None:
        if self._limiter is None:
            self._limiter = RateLimiter(self.settings.global_concurrency, self.settings.min_domain_delay)
            self._persist_lock = asyncio.Lock()
        control = JobControl(job_id)
        control.start()
        error: Optional[str] = None
        try:
            job_info = await asyncio.to_thread(self._load_job, job_id)
            if job_info is None:
                return
            jtype, params = job_info
            log.info("job %s (%s) started", job_id, jtype)
            if jtype == "directory":
                await self._run_directory(job_id, params, control)
            else:
                await self._run_crawl(job_id, params, control)
            if params.get("validate_mx", True) and not control.cancelled:
                await self._validate_job_leads(job_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s crashed", job_id)
            error = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            await control.stop()
            await asyncio.to_thread(self._finish, job_id, error)

    @staticmethod
    def _load_job(job_id: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            return (job.type, dict(job.params or {})) if job else None

    @staticmethod
    def _finish(job_id: int, error: Optional[str]) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if error:
                job.status, job.error = "failed", error
            elif job.status in ("running", "queued"):
                job.status = "completed"
            if job.status in ("completed", "failed") and not job.finished_at:
                job.finished_at = utcnow()

    def _fetcher(self, delay: float) -> SafeFetcher:
        return SafeFetcher(settings=self.settings, limiter=self._limiter, delay=delay, transport=self.transport, resolver=self.resolver)

    async def _persist(self, fn, *args) -> Any:  # noqa: ANN001
        assert self._persist_lock is not None
        async with self._persist_lock:
            return await asyncio.to_thread(fn, *args)

    # ------------------------------------------------------------------ website / url-list / upload_crawl jobs
    async def _run_crawl(self, job_id: int, params: Dict[str, Any], control: JobControl) -> None:
        def pending() -> List[Tuple[int, str]]:
            with SessionLocal() as db:
                return [(r.id, r.url) for r in db.scalars(select(JobUrl).where(JobUrl.job_id == job_id, JobUrl.status == "pending").order_by(JobUrl.id))]

        todo = await asyncio.to_thread(pending)
        options = CrawlOptions(
            max_pages=params.get("max_pages", 10), max_depth=params.get("max_depth", 2), follow_external=params.get("follow_external", False),
            keywords=params.get("keywords", []), keyword_filter=params.get("keyword_filter", False),
        )
        sem = asyncio.Semaphore(params.get("concurrency", 3))

        async with self._fetcher(params.get("delay", 1.0)) as fetcher:
            async def work(jobu_id: int, url: str) -> None:
                async with sem:
                    await control.wait_if_paused()
                    if control.cancelled:
                        return
                    crawler = WebsiteCrawler(fetcher, CrawlOptions(**vars(options)), settings=self.settings, should_stop=lambda: control.cancelled)
                    try:
                        res = await asyncio.wait_for(crawler.crawl(url), timeout=SITE_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        res = SiteResult(input_url=url, status="failed", error=f"Site took longer than {SITE_TIMEOUT_SECONDS}s and was stopped")
                    except Exception as exc:  # noqa: BLE001
                        log.exception("crawl failed for %s", url)
                        res = SiteResult(input_url=url, status="failed", error=f"Unexpected error: {type(exc).__name__}")
                    if control.cancelled:
                        return
                    await self._persist(self._persist_site, job_id, jobu_id, res)

            await asyncio.gather(*(work(i, u) for i, u in todo))

    @staticmethod
    def _persist_site(job_id: int, jobu_id: int, res: SiteResult) -> None:
        with session_scope() as db:
            job_manager.persist_site_result(db, job_id, jobu_id, res)

    # ------------------------------------------------------------------ directory jobs
    async def _run_directory(self, job_id: int, params: Dict[str, Any], control: JobControl) -> None:
        def pending() -> List[Tuple[int, str]]:
            with SessionLocal() as db:
                return [(r.id, r.url) for r in db.scalars(select(JobUrl).where(JobUrl.job_id == job_id, JobUrl.status == "pending").order_by(JobUrl.id))]

        todo = await asyncio.to_thread(pending)
        delay = max(params.get("delay", 1.5), self.settings.min_domain_delay)
        d_opts = DirectoryOptions(max_pages=params.get("max_pages", 5), delay=delay, crawl_websites=params.get("crawl_websites", False), max_sites=params.get("max_sites", 25))
        c_opts = CrawlOptions(max_pages=min(params.get("max_pages", 5), 6), max_depth=1, keywords=params.get("keywords", []))
        async with self._fetcher(delay) as fetcher:
            for jobu_id, url in todo:  # directories are processed one at a time, politely
                await control.wait_if_paused()
                if control.cancelled:
                    return
                scraper = DirectoryScraper(fetcher, DirectoryOptions(**vars(d_opts)), settings=self.settings, should_stop=lambda: control.cancelled)
                try:
                    res = await asyncio.wait_for(scraper.scrape(url), timeout=SITE_TIMEOUT_SECONDS * 2)
                except Exception as exc:  # noqa: BLE001
                    from app.services.directory_scraper import DirectoryResult

                    res = DirectoryResult(start_url=url, status="failed", error=f"Unexpected error: {type(exc).__name__}")
                site_results: List[Tuple[Any, SiteResult]] = []
                if d_opts.crawl_websites and res.status == "success":
                    targets = [r for r in res.records if not r.emails and r.website][: d_opts.max_sites]
                    for rec in targets:
                        if control.cancelled:
                            break
                        await control.wait_if_paused()
                        crawler = WebsiteCrawler(fetcher, CrawlOptions(**vars(c_opts)), settings=self.settings, should_stop=lambda: control.cancelled)
                        try:
                            site_results.append((rec, await asyncio.wait_for(crawler.crawl(rec.website), timeout=SITE_TIMEOUT_SECONDS)))
                        except Exception:  # noqa: BLE001
                            continue
                if control.cancelled:
                    return
                await self._persist(self._persist_directory, job_id, jobu_id, res, site_results)

    @staticmethod
    def _persist_directory(job_id: int, jobu_id: int, res, site_results) -> None:  # noqa: ANN001
        with session_scope() as db:
            job_manager.persist_directory_result(db, job_id, jobu_id, res, site_results)

    # ------------------------------------------------------------------ MX validation after the crawl
    async def _validate_job_leads(self, job_id: int) -> None:
        def load() -> List[Tuple[int, str]]:
            with SessionLocal() as db:
                return [(i, e) for i, e in db.execute(select(Lead.id, Lead.email).where(Lead.job_id == job_id, Lead.verification_status.in_((STATUS_SYNTAX_OK, STATUS_UNVERIFIED))))]

        rows = await asyncio.to_thread(load)
        if not rows:
            return
        validator = EmailValidator(lookup=self.mx_lookup)
        results = await validator.validate_many([e for _, e in rows], check_mx=True)

        def save() -> None:
            with session_scope() as db:
                for lead_id, email in rows:
                    r = results.get(email.lower())
                    if r:
                        db.execute(update(Lead).where(Lead.id == lead_id).values(verification_status=r.status, verification_detail=r.detail))

        await asyncio.to_thread(save)
