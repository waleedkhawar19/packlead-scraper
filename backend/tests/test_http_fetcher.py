import httpx
import pytest

from app.utils.http import FetchError, SafeFetcher
from tests.conftest import PUBLIC_IP, html, make_transport, public_resolver


def fetcher(site, calls=None, **kw):
    return SafeFetcher(transport=make_transport(site, calls), resolver=public_resolver, delay=0, retries=kw.pop("retries", 0), backoff=0, **kw)


async def test_fetch_ok_and_connects_to_validated_ip_with_original_host_header():
    calls = []
    async with fetcher({("acme.com", "/"): (200, html("hi"), {})}, calls) as f:
        res = await f.fetch("https://acme.com/")
    assert res.status_code == 200 and "hi" in res.text
    assert calls == [("acme.com", "/", PUBLIC_IP)]  # DNS pinning: request went to the IP, Host header kept


async def test_timeout_is_reported_as_timeout_error():
    async with fetcher({("slow.com", "/"): (200, httpx.ReadTimeout("slow"), {})}) as f:
        with pytest.raises(FetchError) as e:
            await f.fetch("https://slow.com/")
    assert e.value.kind == "timeout"


async def test_connection_errors_become_network_errors():
    async with fetcher({("down.com", "/"): (200, httpx.ConnectError("refused"), {})}) as f:
        with pytest.raises(FetchError) as e:
            await f.fetch("https://down.com/")
    assert e.value.kind == "network"


async def test_temporary_failures_are_retried_then_succeed():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(503) if attempts["n"] < 3 else httpx.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})

    f = SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver, delay=0, retries=2, backoff=0)
    async with f:
        res = await f.fetch("https://flaky.com/")
    assert res.status_code == 200 and attempts["n"] == 3


async def test_retry_gives_up_after_limit():
    f = SafeFetcher(transport=httpx.MockTransport(lambda r: httpx.Response(503)), resolver=public_resolver, delay=0, retries=1, backoff=0)
    async with f:
        res = await f.fetch("https://flaky.com/")
    assert res.status_code == 503  # final status is returned to the caller, who decides what to do


async def test_redirect_into_private_network_is_blocked():
    site = {("acme.com", "/"): (302, "", {"location": "http://169.254.169.254/latest/meta-data/"})}
    async with fetcher(site) as f:
        with pytest.raises(FetchError) as e:
            await f.fetch("https://acme.com/")
    assert e.value.kind == "unsafe"


async def test_redirect_to_hostname_resolving_privately_is_blocked():
    async def resolver(host, port):
        return ["10.0.0.9"] if host == "evil.com" else [PUBLIC_IP]

    site = {("acme.com", "/"): (301, "", {"location": "https://evil.com/"})}
    f = SafeFetcher(transport=make_transport(site), resolver=resolver, delay=0, retries=0, backoff=0)
    async with f:
        with pytest.raises(FetchError) as e:
            await f.fetch("https://acme.com/")
    assert e.value.kind == "unsafe"


async def test_redirect_loop_and_too_many_redirects():
    site = {("a.com", "/"): (302, "", {"location": "/"}), ("b.com", "/0"): (302, "", {"location": "/1"})}
    site.update({("b.com", f"/{i}"): (302, "", {"location": f"/{i + 1}"}) for i in range(20)})
    async with fetcher(site) as f:
        with pytest.raises(FetchError) as e:
            await f.fetch("https://a.com/")
        assert e.value.kind == "redirect_loop"
        with pytest.raises(FetchError) as e2:
            await f.fetch("https://b.com/0")
        assert e2.value.kind == "redirect_loop" and "Too many" in e2.value.message


async def test_unsupported_content_type_is_rejected():
    site = {("acme.com", "/logo.png"): (200, b"\x89PNG", {"content-type": "image/png"})}
    async with fetcher(site) as f:
        with pytest.raises(FetchError) as e:
            await f.fetch("https://acme.com/logo.png")
    assert e.value.kind == "unsupported_content"


async def test_oversized_pages_are_truncated_not_loaded_fully():
    moderately_big = "<p>" + "x" * 25_000 + "</p>"
    huge = "<p>" + "x" * 500_000 + "</p>"
    async with fetcher({("acme.com", "/"): (200, moderately_big, {}), ("acme.com", "/huge"): (200, huge, {})}) as f:
        res = await f.fetch("https://acme.com/", max_bytes=10_000)
        assert res.truncated and len(res.text) <= 10_000  # reading stops at the limit
        with pytest.raises(FetchError) as e:  # declared size far beyond the limit is refused outright
            await f.fetch("https://acme.com/huge", max_bytes=10_000)
        assert e.value.kind == "too_large"


async def test_private_start_url_is_blocked_before_any_request():
    calls = []
    async with fetcher({}, calls) as f:
        with pytest.raises(FetchError) as e:
            await f.fetch("http://10.0.0.1/")
    assert e.value.kind == "unsafe" and calls == []
