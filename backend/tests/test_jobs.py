import asyncio

import httpx
import pytest

from app.models.job import Job, JobUrl
from app.models.lead import Lead
from app.services import job_manager
from app.services.job_manager import JobError
from app.workers.runner import JobRunner
from tests.conftest import html, public_resolver


async def fake_mx(domain):
    return "mx", [f"mail.{domain}"], ""


def runner(**kw):
    return JobRunner(mx_lookup=fake_mx, **kw)


async def run_all(r):
    n = 0
    while await r.run_next():
        n += 1
    return n


def create(db, urls, **params):
    p = {"max_pages": 10, "max_depth": 2, "delay": 0, "concurrency": 2, "validate_mx": True, **params}
    return job_manager.create_crawl_job(db, name="test", urls=urls, params=p)


async def test_job_runs_against_fixture_site_and_tracks_progress(db, fixture_site):
    job, counts = create(db, [fixture_site, "http://localhost:8099/", "not a url", "http://127.0.0.1:8099"])
    assert counts == {"valid": 2, "invalid": 1, "duplicates": 1} and job.status == "queued" and job.is_test
    assert job.total_urls == 3 and job.processed_urls == 1 and job.failed_urls == 1  # invalid URL is recorded immediately

    seen = []
    r = runner()

    async def watch():
        while True:
            db.expire_all()
            seen.append(job_manager.progress(db, db.get(Job, job.id))["percent"])
            await asyncio.sleep(0.05)

    task = asyncio.create_task(watch())
    await run_all(r)
    task.cancel()
    db.expire_all()
    job = db.get(Job, job.id)
    p = job_manager.progress(db, job)
    assert job.status == "completed" and p["percent"] == 100.0 and p["pending_urls"] == 0
    assert (job.processed_urls, job.successful_urls, job.failed_urls) == (3, 2, 1)
    assert seen == sorted(seen)  # progress never goes backwards
    assert job.emails_found == 8 and job.unique_leads == 8 and job.duplicates_removed == 0 and job.pages_visited >= 4
    leads = db.query(Lead).all()
    assert len(leads) == 8 and all(l.is_test for l in leads)
    assert {l.verification_status for l in leads} == {"Domain MX Found"}
    nw = db.query(Lead).filter_by(email="sales@northwind-box.test").one()
    assert (nw.business_name, nw.state, nw.country, nw.category, nw.category_source) == ("Northwind Box Co.", "Nevada", "United States", "Packaging Distributor", "auto")
    assert nw.category_evidence["keywords"] and nw.contact_page_url.endswith("/contact.html") and nw.source_url.endswith("/contact.html")
    assert nw.original_email == "Sales@Northwind-Box.test"
    failed = db.query(JobUrl).filter_by(job_id=job.id, status="failed").one()
    assert "Invalid URL" in failed.error


async def test_rerun_counts_duplicates_and_keeps_all_sources(db, fixture_site):
    create(db, [fixture_site])
    await run_all(runner())
    job2, _ = create(db, [fixture_site])
    await run_all(runner())
    db.expire_all()
    job2 = db.get(Job, job2.id)
    assert job2.unique_leads == 0 and job2.duplicates_removed == 7
    assert db.query(Lead).count() == 7  # still one row per email
    lead = db.query(Lead).filter_by(email="info@northwind-box.test").one()
    assert [s.source_url.rsplit("/", 1)[-1] for s in lead.sources] == ["contact.html"]  # same source is not recorded twice


async def test_cancel_before_start_means_it_never_runs(db):
    job, _ = create(db, ["acme.com"])
    job_manager.cancel_job(db, job.id)
    assert await runner().run_next() is False
    assert db.get(Job, job.id).status == "cancelled" and db.get(Job, job.id).finished_at


def test_status_transitions(db):
    job, _ = create(db, ["acme.com"])
    assert job_manager.pause_job(db, job.id).status == "paused"
    assert job_manager.resume_job(db, job.id).status == "queued"  # never started
    job_manager.cancel_job(db, job.id)
    for fn in (job_manager.pause_job, job_manager.resume_job, job_manager.cancel_job):
        with pytest.raises(JobError):
            fn(db, job.id)
    with pytest.raises(JobError):
        job_manager.get_job(db, 9999)


def test_requeue_interrupted_jobs(db):
    job, _ = create(db, ["acme.com"])
    job.status = "running"
    db.commit()
    assert JobRunner.requeue_interrupted() == 1
    db.expire_all()
    assert db.get(Job, job.id).status == "queued"


async def test_cancel_while_running_stops_remaining_sites(db):
    async def handler(request: httpx.Request):
        await asyncio.sleep(0.35)
        return httpx.Response(200, text=html("Mail: hi@acme.com"), headers={"content-type": "text/html"})

    urls = [f"site{i}.com" for i in range(8)]
    job, _ = create(db, urls, concurrency=1, max_pages=1, validate_mx=False)
    r = runner(transport=httpx.MockTransport(handler), resolver=public_resolver)

    async def canceller():
        await asyncio.sleep(1.2)
        await asyncio.to_thread(lambda: job_manager.cancel_job(__import__("app.database", fromlist=["SessionLocal"]).SessionLocal(), job.id))

    task = asyncio.create_task(canceller())
    await asyncio.wait_for(run_all(r), timeout=30)
    await task
    db.expire_all()
    job = db.get(Job, job.id)
    pending = db.query(JobUrl).filter_by(job_id=job.id, status="pending").count()
    assert job.status == "cancelled" and 0 < job.processed_urls < 8 and pending > 0


async def test_pause_blocks_progress_until_resume(db):
    job, _ = create(db, [f"s{i}.com" for i in range(3)], concurrency=1, max_pages=1, validate_mx=False)

    async def handler(request: httpx.Request):
        return httpx.Response(200, text=html("Mail: hi@acme.com"), headers={"content-type": "text/html"})

    job_manager.pause_job(db, job.id)
    r = runner(transport=httpx.MockTransport(handler), resolver=public_resolver)
    assert await r.run_next() is False  # paused jobs are not picked up
    job_manager.resume_job(db, job.id)
    assert await asyncio.wait_for(r.run_next(), 30) is True
    db.expire_all()
    assert db.get(Job, job.id).status == "completed"


def test_delete_job_keeps_leads_unless_asked(db):
    from app.services.lead_deduplicator import LeadCandidate, upsert_leads

    job, _ = create(db, ["acme.com"])
    upsert_leads(db, [LeadCandidate("a1@acme.com", source_type="website")], job_id=job.id)
    db.commit()
    assert job_manager.delete_job(db, job.id) == {"leads_deleted": 0}
    assert db.query(Lead).count() == 1 and db.query(Lead).one().job_id is None
    job2, _ = create(db, ["beta.com"])
    upsert_leads(db, [LeadCandidate("b1@beta.com", source_type="website")], job_id=job2.id)
    db.commit()
    assert job_manager.delete_job(db, job2.id, delete_leads=True) == {"leads_deleted": 1}
    assert db.query(Lead).count() == 1


def test_url_limit_and_empty_input(db, monkeypatch):
    with pytest.raises(JobError):
        job_manager.create_crawl_job(db, name="x", urls=[], params={})
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_urls_per_job", 2)
    with pytest.raises(JobError):
        create(db, ["a.com", "b.com", "c.com"])


def test_params_are_clamped_to_server_limits():
    p = job_manager.clamp_params({"max_pages": 10_000, "max_depth": 99, "delay": 0, "concurrency": 500})
    assert p["max_pages"] == 100 and p["max_depth"] == 4 and p["concurrency"] == 10


async def test_directory_job_with_website_crawl(db, fixture_site):
    job, _ = job_manager.create_directory_job(db, name="dir", urls=[fixture_site + "/directory/"], params={"delay": 0, "max_pages": 5, "crawl_websites": True, "max_sites": 5, "validate_mx": False})
    await asyncio.wait_for(run_all(runner()), 60)
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.status == "completed" and job.successful_urls == 1 and job.pages_visited == 3
    emails = {l.email: l for l in db.query(Lead).all()}
    assert {"contact@alphapack.test", "info@betabottling.test", "hello@gammafulfill.test"} <= set(emails)
    green = emails["wholesale@greenleaf-foods.test"]  # no email in directory -> found by crawling the listed website
    assert green.business_name == "Greenleaf Organic Foods" and green.source_type == "directory" and "business website" in green.notes
    assert emails["contact@alphapack.test"].category == "Packaging Distributor" and emails["contact@alphapack.test"].state == "Colorado"
