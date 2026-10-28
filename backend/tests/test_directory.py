from app.config import get_settings
from app.services.directory_scraper import DirectoryOptions, DirectoryScraper, ADAPTERS
from app.utils.http import SafeFetcher
from tests.conftest import html, make_transport, public_resolver


def scraper(site, **opts):
    f = SafeFetcher(transport=make_transport(site), resolver=public_resolver, delay=0, retries=0, backoff=0)
    return DirectoryScraper(f, DirectoryOptions(delay=0, **opts)), f


async def test_fixture_directory_parses_cards_follows_pagination_and_dedupes(fixture_site):
    async with SafeFetcher(settings=get_settings(), delay=0, retries=0, backoff=0) as f:
        res = await DirectoryScraper(f, DirectoryOptions(delay=0, max_pages=5)).scrape(fixture_site + "/directory/")
    assert res.status == "success" and res.pages_visited == 3
    names = [r.business_name for r in res.records]
    assert sorted(names) == ["Alpha Pack Supply", "Beta Bottling Works", "Gamma Fulfillment", "Greenleaf Organic Foods"]  # Alpha appears on 2 pages, kept once
    alpha = next(r for r in res.records if r.business_name == "Alpha Pack Supply")
    assert alpha.emails == ["contact@alphapack.test"] and alpha.website == "http://alphapack.test/"
    assert (alpha.city, alpha.state, alpha.category) == ("Denver", "Colorado", "Packaging Distributor")
    assert alpha.source_url.endswith("/directory/")
    green = next(r for r in res.records if r.business_name.startswith("Greenleaf"))
    assert green.emails == [] and green.website == "http://localhost:8099/"  # no email listed -> not invented


async def test_page_limit(fixture_site):
    async with SafeFetcher(settings=get_settings(), delay=0, retries=0, backoff=0) as f:
        res = await DirectoryScraper(f, DirectoryOptions(delay=0, max_pages=1)).scrape(fixture_site + "/directory/")
    assert res.pages_visited == 1 and "Page limit" in res.note


async def test_robots_disallow_skips_directory():
    site = {("dir.com", "/robots.txt"): (200, "User-agent: *\nDisallow: /listings\n", {}), ("dir.com", "/listings"): (200, html("<p>x</p>"), {})}
    s, f = scraper(site)
    async with f:
        res = await s.scrape("https://dir.com/listings")
    assert res.status == "skipped" and "robots.txt" in res.error


async def test_login_captcha_and_forbidden_are_skipped_not_bypassed():
    site = {
        ("a.com", "/"): (200, html('<form><input type="password"></form>'), {}),
        ("b.com", "/"): (200, html('<div class="g-recaptcha"></div>'), {}),
        ("c.com", "/"): (403, "Forbidden", {}),
        ("d.com", "/"): (429, "slow down", {}),
    }
    for host, needle in (("a.com", "login"), ("b.com", "CAPTCHA"), ("c.com", "403"), ("d.com", "429")):
        s, f = scraper(site)
        async with f:
            res = await s.scrape(host)
        assert res.status == "skipped" and needle.lower() in res.error.lower(), (host, res.error)


async def test_json_ld_adapter_is_chosen_for_structured_listings():
    ld = '<script type="application/ld+json">[{"@type":"LocalBusiness","name":"One Co","email":"a@one.co","url":"https://one.co"},{"@type":"LocalBusiness","name":"Two Co","email":"b@two.co","address":{"addressLocality":"Miami","addressRegion":"FL"}}]</script>'
    s, f = scraper({("dir.com", "/"): (200, html(ld), {})})
    async with f:
        res = await s.scrape("dir.com")
    assert res.adapter == "schema.org JSON-LD" and [r.emails for r in res.records] == [["a@one.co"], ["b@two.co"]] and res.records[1].state == "Florida"


async def test_unparseable_layout_returns_clear_note_not_fake_data():
    s, f = scraper({("dir.com", "/"): (200, html("<p>Just a story about boxes, no contacts.</p>"), {})})
    async with f:
        res = await s.scrape("dir.com")
    assert res.status == "success" and res.records == [] and "custom adapter" in res.note


async def test_pagination_never_leaves_the_directory_host():
    page = html('<ul><li><h3>Biz</h3><a href="mailto:x1@biz.com">x1@biz.com</a></li></ul><a rel="next" href="https://elsewhere.com/p2">Next</a>')
    s, f = scraper({("dir.com", "/"): (200, page, {})})
    async with f:
        res = await s.scrape("dir.com")
    assert res.pages_visited == 1


def test_adapter_registry_has_generic_fallback_last():
    assert ADAPTERS[-1].name == "generic listing parser"
