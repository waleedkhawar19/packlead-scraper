import httpx
import pytest

from app.services import category_classifier
from app.services.website_crawler import CrawlOptions, WebsiteCrawler
from app.utils.http import SafeFetcher
from tests.conftest import html, make_transport, public_resolver


def crawler_for(site, calls=None, **opts):
    fetcher = SafeFetcher(transport=make_transport(site, calls), resolver=public_resolver, delay=0, retries=0, backoff=0)
    return WebsiteCrawler(fetcher, CrawlOptions(**opts)), fetcher


SITE = {
    ("acme.com", "/"): (200, html('<h1>Acme</h1><a href="/contact">Contact</a><a href="/about-us">About</a><a href="https://other.com/">x</a><a href="/products?sort=a&page=2&x=1">p</a>', "Acme Boxes"), {}),
    ("acme.com", "/contact"): (200, html('Email <a href="mailto:Sales@Acme.com">us</a> or info@acme.com. Tel (303) 555-0100. Denver, CO 80202'), {}),
    ("acme.com", "/about-us"): (200, html("About us: hr@acme.com"), {}),
    ("other.com", "/"): (200, html("elsewhere@other.com"), {}),
}


async def test_finds_emails_on_contact_pages_and_records_source_url_and_time():
    c, f = crawler_for(SITE)
    async with f:
        res = await c.crawl("acme.com")
    assert res.status == "success"
    assert {e.email for e in res.emails} == {"sales@acme.com", "info@acme.com", "hr@acme.com"}
    by = {e.email: e for e in res.emails}
    assert by["sales@acme.com"].source_url == "https://acme.com/contact" and by["sales@acme.com"].original == "Sales@Acme.com"
    assert by["sales@acme.com"].collected_at is not None
    assert res.contact_page_url == "https://acme.com/contact"
    assert (res.business_name, res.phone, res.state) == ("Acme Boxes", "(303) 555-0100", "Colorado")


async def test_does_not_leave_the_site_by_default_but_can_when_enabled():
    c, f = crawler_for(SITE)
    async with f:
        assert "elsewhere@other.com" not in {e.email for e in (await c.crawl("acme.com")).emails}
    c, f = crawler_for(SITE, follow_external=True)
    async with f:
        assert "elsewhere@other.com" in {e.email for e in (await c.crawl("acme.com")).emails}


async def test_page_limit_and_depth_limit():
    c, f = crawler_for(SITE, max_pages=1)
    async with f:
        res = await c.crawl("acme.com")
    assert res.pages_visited == 1 and res.emails == []
    c, f = crawler_for(SITE, max_depth=0)
    async with f:
        assert (await c.crawl("acme.com")).pages_visited == 1


async def test_robots_txt_is_respected():
    site = dict(SITE)
    site[("acme.com", "/robots.txt")] = (200, "User-agent: *\nDisallow: /contact\n", {"content-type": "text/plain"})
    calls = []
    c, f = crawler_for(site, calls)
    async with f:
        res = await c.crawl("acme.com")
    assert "sales@acme.com" not in {e.email for e in res.emails}
    assert ("acme.com", "/contact", "93.184.216.34") not in calls
    assert res.pages_skipped >= 1


async def test_robots_disallow_all_skips_the_site():
    site = {("acme.com", "/robots.txt"): (200, "User-agent: *\nDisallow: /\n", {"content-type": "text/plain"}), **SITE}
    c, f = crawler_for(site)
    async with f:
        res = await c.crawl("acme.com")
    assert res.status == "skipped" and "robots" in res.error.lower()


async def test_probes_common_contact_paths_when_homepage_has_no_links():
    site = {("bare.com", "/"): (200, html("<p>Welcome</p>"), {}), ("bare.com", "/contact"): (200, html("Mail: office@bare.com"), {})}
    c, f = crawler_for(site)
    async with f:
        res = await c.crawl("bare.com")
    assert [e.email for e in res.emails] == ["office@bare.com"]


async def test_empty_result_is_success_with_note_not_error():
    c, f = crawler_for({("empty.com", "/"): (200, html("<p>Nothing here</p>"), {})})
    async with f:
        res = await c.crawl("empty.com")
    assert res.status == "success" and res.emails == [] and "No public emails" in res.note


@pytest.mark.parametrize(
    "site,url,status,needle",
    [
        ({("gone.com", "/"): (404, "x", {})}, "gone.com", "failed", "404"),
        ({("locked.com", "/"): (403, "x", {})}, "locked.com", "skipped", "403"),
        ({("slow.com", "/"): (200, httpx.ReadTimeout("t"), {})}, "slow.com", "failed", "Timed out"),
        ({}, "http://10.0.0.1/", "skipped", "Blocked"),
        ({}, "not a url", "failed", "Invalid URL"),
        ({("bin.com", "/"): (200, b"\x00\x01", {"content-type": "application/octet-stream"})}, "bin.com", "failed", "Unsupported"),
    ],
)
async def test_failures_are_reported_gracefully(site, url, status, needle):
    c, f = crawler_for(site)
    async with f:
        res = await c.crawl(url)
    assert res.status == status and needle in (res.error or "")


async def test_http_fallback_when_https_is_unavailable():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.scheme)
        if request.url.scheme == "https":
            raise httpx.ConnectError("no tls")
        return httpx.Response(200, text=html("Mail: hi@oldsite.com"), headers={"content-type": "text/html"})

    f = SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver, delay=0, retries=0, backoff=0)
    async with f:
        res = await WebsiteCrawler(f, CrawlOptions()).crawl("oldsite.com")
    assert [e.email for e in res.emails] == ["hi@oldsite.com"] and "http" in calls


async def test_keyword_filter_discards_non_matching_sites():
    site = {("acme.com", "/"): (200, html("We sell custom packaging. Mail sales@acme.com"), {})}
    c, f = crawler_for(site, keywords=["custom packaging"], keyword_filter=True)
    async with f:
        res = await c.crawl("acme.com")
    assert res.status == "success" and res.matched_keywords == ["custom packaging"]
    c, f = crawler_for(site, keywords=["food manufacturer"], keyword_filter=True)
    async with f:
        res = await c.crawl("acme.com")
    assert res.status == "skipped" and res.emails == []


async def test_cancellation_stops_crawl():
    c, f = crawler_for(SITE)
    c.should_stop = lambda: True
    async with f:
        res = await c.crawl("acme.com")
    assert res.pages_visited == 1 and "Stopped early" in res.note


# ------------------------------------------------------------------ against the real local fixture website
async def test_fixture_site_northwind(fixture_site):
    from app.config import get_settings

    async with SafeFetcher(settings=get_settings(), delay=0, retries=0, backoff=0) as f:
        res = await WebsiteCrawler(f, CrawlOptions(max_pages=10, max_depth=2)).crawl(fixture_site)
    got = {e.email for e in res.emails}
    assert got == {"sales@northwind-box.test", "info@northwind-box.test", "orders@northwind-box.test", "support@northwind-box.test",
                   "press@northwind-box.test", "hr@northwind-box.test", "products@northwind-box.test"}
    assert "secret@northwind-box.test" not in got  # /private/ is disallowed by the fixture's robots.txt
    assert "noise@should-not-be-found.test" not in got  # emails inside <script> are ignored
    assert res.business_name == "Northwind Box Co." and res.phone and res.city == "Reno" and res.state == "Nevada"
    assert res.contact_page_url.endswith("/contact.html")
    assert not any("cart" in p or "brochure" in p for p in res.page_log if p.startswith("200"))
    guess = category_classifier.classify(res.context_text)
    assert guess and guess["category"] == "Packaging Distributor" and guess["keywords"]


async def test_fixture_site_respects_max_pages(fixture_site):
    from app.config import get_settings

    async with SafeFetcher(settings=get_settings(), delay=0, retries=0, backoff=0) as f:
        res = await WebsiteCrawler(f, CrawlOptions(max_pages=2, max_depth=2)).crawl(fixture_site)
    assert res.pages_visited <= 2


async def test_fixture_greenleaf_classification_is_evidence_based(fixture_site):
    from app.config import get_settings

    async with SafeFetcher(settings=get_settings(), delay=0, retries=0, backoff=0) as f:
        res = await WebsiteCrawler(f, CrawlOptions()).crawl("http://localhost:8099/")
    assert {e.email for e in res.emails} == {"wholesale@greenleaf-foods.test"}
    guess = category_classifier.classify(res.context_text)
    assert guess["category"] in ("Food & Beverage", "E-commerce Store") and len(guess["snippets"]) >= 1


def test_classifier_requires_evidence():
    assert category_classifier.classify("Welcome to our company page. We are great people who like things a lot of the time.") is None
    assert category_classifier.classify("short") is None
    one_hit = "We run a small shop. " * 3 + "Our wholesale team is friendly and the weather is nice today in town."
    assert category_classifier.classify(one_hit) is None  # a single keyword once is not enough
    custom = category_classifier.classify("We produce sustainable mushroom foam inserts and mushroom packaging for brands.", {"Eco Packaging": ["mushroom foam", "mushroom packaging"]})
    assert custom["category"] == "Eco Packaging"
