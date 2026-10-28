"""The single, SSRF-safe HTTP client used by every crawler.

Guarantees:
* every hop (initial URL and each redirect) is validated with ``validate_destination``;
* the TCP connection goes to the *validated IP* (DNS pinning) with the original Host/SNI preserved;
* bounded redirects, response size, content type and time;
* per-domain minimum delay and a global concurrency cap;
* retry with backoff for temporary network errors only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import UnicodeDammit

from app.config import Settings, get_settings
from app.utils.url_safety import InvalidURLError, Resolver, UnsafeURLError, validate_destination

log = logging.getLogger("packlead.http")

HTML_TYPES = ("text/html", "application/xhtml+xml")
TEXT_TYPES = ("text/plain",)
REDIRECT_CODES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    """Fetch failed. ``kind`` is one of: timeout, network, blocked, unsafe, invalid_url, status,
    unsupported_content, too_large, redirect_loop."""

    def __init__(self, kind: str, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status_code: int
    content_type: str
    text: str
    headers: Dict[str, str] = field(default_factory=dict)
    redirects: List[str] = field(default_factory=list)
    truncated: bool = False


class RateLimiter:
    """Global concurrency semaphore + minimum delay between requests to the same host."""

    def __init__(self, global_concurrency: int, default_delay: float):
        self._sem = asyncio.Semaphore(max(1, global_concurrency))
        self._default_delay = default_delay
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last: Dict[str, float] = {}
        self._delays: Dict[str, float] = {}

    def set_delay(self, host: str, delay: float) -> None:
        self._delays[host] = max(self._delays.get(host, 0.0), delay)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._sem

    async def wait_turn(self, host: str, delay: Optional[float] = None) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait_for = max(delay if delay is not None else self._default_delay, self._delays.get(host, 0.0))
            elapsed = time.monotonic() - self._last.get(host, 0.0)
            if elapsed < wait_for:
                await asyncio.sleep(wait_for - elapsed)
            self._last[host] = time.monotonic()


class SafeFetcher:
    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        limiter: Optional[RateLimiter] = None,
        delay: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        resolver: Optional[Resolver] = None,
        retries: Optional[int] = None,
        backoff: Optional[float] = None,
    ):
        self.settings = settings or get_settings()
        s = self.settings
        self.delay = max(s.min_domain_delay, delay if delay is not None else s.min_domain_delay)
        self.limiter = limiter or RateLimiter(s.global_concurrency, self.delay)
        self.resolver = resolver
        self.retries = s.request_retries if retries is None else retries
        self.backoff = s.retry_backoff_seconds if backoff is None else backoff
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(s.request_timeout, connect=min(10.0, s.request_timeout)),
            follow_redirects=False,  # we follow manually so every hop is validated
            headers={
                "User-Agent": s.user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
                "Accept-Language": "en-US,en;q=0.8",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SafeFetcher":
        return self

    async def __aexit__(self, *exc) -> None:  # noqa: ANN002
        await self.aclose()

    async def fetch(
        self,
        url: str,
        *,
        accept: Sequence[str] = HTML_TYPES,
        max_bytes: Optional[int] = None,
        delay: Optional[float] = None,
    ) -> FetchResult:
        s = self.settings
        max_bytes = max_bytes or s.max_page_bytes
        current = url
        chain: List[str] = []
        for _hop in range(s.max_redirects + 1):
            resp = await self._request_with_retries(current, accept, max_bytes, delay)
            if resp.status_code in REDIRECT_CODES:
                location = resp.headers.get("location")
                if not location:
                    raise FetchError("status", f"HTTP {resp.status_code} redirect without Location", resp.status_code)
                nxt = urljoin(current, location)
                if nxt in chain or nxt == current:
                    raise FetchError("redirect_loop", "Redirect loop detected")
                chain.append(current)
                current = nxt
                continue
            resp.redirects = chain
            resp.url = current
            return resp
        raise FetchError("redirect_loop", f"Too many redirects (more than {s.max_redirects})")

    # ------------------------------------------------------------------ internals
    async def _request_with_retries(self, url: str, accept: Sequence[str], max_bytes: int, delay: Optional[float]) -> FetchResult:
        attempt = 0
        while True:
            try:
                result = await self._single_request(url, accept, max_bytes, delay)
                if result.status_code in (429, 502, 503, 504) and attempt < self.retries:
                    raise _Retryable(f"HTTP {result.status_code}", result.status_code)
                return result
            except _Retryable as exc:
                err = FetchError("status", str(exc), exc.status_code)
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                err = FetchError("timeout", f"Timed out after {self.settings.request_timeout:.0f}s ({type(exc).__name__})")
            except (httpx.TransportError, OSError) as exc:
                err = FetchError("network", f"Network error: {type(exc).__name__}: {exc}")
            if attempt >= self.retries:
                raise err
            attempt += 1
            wait = self.backoff * (2 ** (attempt - 1))
            log.info("retrying %s in %.1fs (%s)", url, wait, err.message)
            await asyncio.sleep(wait)

    async def _single_request(self, url: str, accept: Sequence[str], max_bytes: int, delay: Optional[float]) -> FetchResult:
        try:
            ips = await validate_destination(url, self.resolver)
        except UnsafeURLError as exc:
            raise FetchError("unsafe", f"Blocked for safety: {exc}") from exc
        except InvalidURLError as exc:
            raise FetchError("invalid_url", str(exc)) from exc

        parts = urlsplit(url)
        host = parts.hostname or ""
        await self.limiter.wait_turn(host, delay if delay is not None else self.delay)

        # DNS pinning: connect to the validated IP while keeping Host header and TLS SNI.
        pinned = httpx.URL(url)
        extensions: Dict[str, object] = {}
        headers: Dict[str, str] = {}
        if ips and ips[0] != host:
            pinned = pinned.copy_with(host=ips[0])
            headers["Host"] = parts.netloc.rsplit("@", 1)[-1]
            extensions["sni_hostname"] = host

        async with self.limiter.semaphore:
            async with self._client.stream("GET", pinned, headers=headers, extensions=extensions) as response:
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                code = response.status_code
                hdrs = {k.lower(): v for k, v in response.headers.items()}
                if code in REDIRECT_CODES or code >= 400:
                    return FetchResult(url=url, status_code=code, content_type=ctype, text="", headers=hdrs)
                if accept and ctype and not any(ctype == a or ctype.startswith(a) for a in accept):
                    raise FetchError("unsupported_content", f"Unsupported content type '{ctype}'", code)
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes * 3:
                    raise FetchError("too_large", f"Page is larger than the {max_bytes // 1000} KB limit", code)
                chunks: List[bytes] = []
                size = 0
                truncated = False
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        chunks.append(chunk[: max(0, max_bytes - (size - len(chunk)))])
                        truncated = True
                        break
                    chunks.append(chunk)
                body = b"".join(chunks)
                text = _decode(body, response.headers.get("content-type", ""))
                return FetchResult(url=url, status_code=code, content_type=ctype, text=text, headers=hdrs, truncated=truncated)


class _Retryable(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _decode(body: bytes, content_type_header: str) -> str:
    declared = None
    if "charset=" in content_type_header.lower():
        declared = content_type_header.lower().split("charset=")[-1].split(";")[0].strip().strip("\"'")
    try:
        dammit = UnicodeDammit(body, known_definite_encodings=[declared] if declared else None, is_html=True)
        return dammit.unicode_markup or body.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - never fail a crawl because of an odd encoding
        return body.decode("utf-8", errors="replace")
