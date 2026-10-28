"""Polite, bounded same-site crawler that collects publicly listed business emails.

Order of work for each site: robots.txt -> homepage -> pages most likely to hold contact details
(contact / about / locations / sales / support / team) -> other internal pages while the page budget
lasts. It never leaves the site unless ``follow_external`` is enabled, never revisits a URL, and stops
at ``max_pages`` / ``max_depth``."""
from __future__ import annotations

import heapq
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from app.config import Settings, get_settings
from app.services.email_extractor import FoundEmail, extract_from_html
from app.utils.http import FetchError, FetchResult, SafeFetcher
from app.utils.url_safety import InvalidURLError, normalize_url, registrable_host

log = logging.getLogger("packlead.crawler")

RELEVANT_PATTERNS: List[Tuple[re.Pattern, int]] = [
    (re.compile(r"contact"), 100),
    (re.compile(r"get[-_ ]?in[-_ ]?touch|reach[-_ ]?us|connect[-_ ]?with|talk[-_ ]?to"), 85),
    (re.compile(r"about"), 70),
    (re.compile(r"locations?|find[-_ ]?us|store[-_ ]?locator|visit[-_ ]?us|showroom"), 60),
    (re.compile(r"customer[-_ ]?(service|care)|support|help[-_ ]?center|faq"), 55),
    (re.compile(r"sales|request[-_ ]?(a[-_ ])?quote|get[-_ ]?(a[-_ ])?quote|wholesale|custom"), 50),
    (re.compile(r"team|staff|people|leadership|our[-_ ]story|who[-_ ]we[-_ ]are"), 40),
]
CONTACT_URL_RE = re.compile(r"contact|get-in-touch|reach-us", re.I)
SKIP_EXT = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".zip", ".rar", ".7z", ".gz", ".mp3", ".mp4",
    ".avi", ".mov", ".wmv", ".css", ".js", ".json", ".xml", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dmg", ".apk", ".woff", ".woff2", ".ttf", ".csv", ".rss",
}
SKIP_PATH_RE = re.compile(
    r"/(cart|checkout|login|log-in|signin|sign-in|logout|account|my-account|wp-admin|wp-login|wp-json|feed|cgi-bin|"
    r"tag|tags|author|search|basket|wishlist|compare|admin|cdn-cgi)(/|$)",
    re.I,
)
PROBE_PATHS = ["/contact", "/contact-us", "/about-us", "/about"]


@dataclass
class CrawlOptions:
    max_pages: int = 10
    max_depth: int = 2
    follow_external: bool = False
    keywords: List[str] = field(default_factory=list)
    keyword_filter: bool = False  # only keep emails from sites whose text matches a keyword
    respect_robots: bool = True


@dataclass
class SiteEmail(FoundEmail):
    source_url: str = ""
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


@dataclass
class SiteResult:
    input_url: str
    status: str = "pending"  # success | failed | skipped
    error: Optional[str] = None
    note: str = ""
    root_url: str = ""
    emails: List[SiteEmail] = field(default_factory=list)
    business_name: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    address: str = ""
    contact_page_url: str = ""
    context_text: str = ""
    matched_keywords: List[str] = field(default_factory=list)
    pages_visited: int = 0
    pages_skipped: int = 0
    page_log: List[str] = field(default_factory=list)


class RobotsPolicy:
    """robots.txt decisions with a per-origin cache."""

    def __init__(self, fetcher: SafeFetcher, settings: Settings, enabled: bool = True):
        self.fetcher = fetcher
        self.settings = settings
        self.enabled = enabled
        self._cache: Dict[str, Optional[RobotFileParser]] = {}

    async def _load(self, origin: str) -> Optional[RobotFileParser]:
        if origin in self._cache:
            return self._cache[origin]
        rp: Optional[RobotFileParser] = RobotFileParser()
        try:
            res = await self.fetcher.fetch(origin + "/robots.txt", accept=(), max_bytes=500_000)
            if res.status_code == 200:
                rp.parse(res.text.splitlines())  # type: ignore[union-attr]
            elif res.status_code in (401, 403) or res.status_code >= 500:
                rp.disallow_all = True  # type: ignore[union-attr]  # RFC 9309: unreachable/forbidden -> assume closed
            else:
                rp = None  # 404 etc: no restrictions published
        except FetchError as exc:
            if exc.kind in ("unsafe", "invalid_url"):
                raise
            rp = None  # site unreachable: the page fetch will report the real error
        self._cache[origin] = rp
        if rp is not None:
            delay = rp.crawl_delay(self.settings.robots_product_token) or rp.crawl_delay("*")
            if delay:
                host = urlsplit(origin).hostname or ""
                self.fetcher.limiter.set_delay(host, min(float(delay), self.settings.max_robots_delay))
        return rp

    async def allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        rp = await self._load(origin)
        if rp is None:
            return True
        return rp.can_fetch(self.settings.robots_product_token, url)


def canonical_key(url: str) -> str:
    p = urlsplit(url)
    path = p.path.rstrip("/") or "/"
    return f"{registrable_host(p.hostname or '')}{path}?{p.query}".lower()


def score_link(url: str, anchor: str) -> int:
    p = urlsplit(url)
    hay = f"{p.path.lower()} {anchor.lower()}"
    best = 0
    for pattern, score in RELEVANT_PATTERNS:
        if pattern.search(hay):
            best = max(best, score)
    return best


def should_skip_link(url: str, relevance: int) -> bool:
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        return True
    path = p.path.lower()
    if any(path.endswith(ext) for ext in SKIP_EXT):
        return True
    if SKIP_PATH_RE.search(path) and relevance == 0:
        return True
    if p.query:
        params = parse_qsl(p.query)
        if relevance == 0 and (len(params) > 2 or len(p.query) > 80):
            return True  # filter/sort/calendar URLs: classic crawl traps
        if len(params) > 4:
            return True
    if path.count("/") > 8:
        return True
    return False


class WebsiteCrawler:
    def __init__(
        self,
        fetcher: SafeFetcher,
        options: Optional[CrawlOptions] = None,
        *,
        settings: Optional[Settings] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        robots: Optional[RobotsPolicy] = None,
    ):
        self.settings = settings or get_settings()
        self.fetcher = fetcher
        self.options = options or CrawlOptions()
        self.options.max_pages = max(1, min(self.options.max_pages, self.settings.max_pages_limit))
        self.options.max_depth = max(0, min(self.options.max_depth, self.settings.max_depth_limit))
        self.should_stop = should_stop or (lambda: False)
        self._order_counter = 0
        self.robots = robots or RobotsPolicy(fetcher, self.settings, self.options.respect_robots and self.settings.respect_robots_txt)

    async def crawl(self, input_url: str) -> SiteResult:
        result = SiteResult(input_url=input_url)
        try:
            start = normalize_url(input_url)
        except InvalidURLError as exc:
            result.status, result.error = "failed", f"Invalid URL: {exc}"
            return result

        first = await self._fetch_homepage(start, result)
        if first is None:
            return result

        root = first.url
        result.root_url = _origin(root)
        root_host = registrable_host(urlsplit(root).hostname or "")
        visited: Set[str] = {canonical_key(root), canonical_key(start)}
        heap: List[Tuple[int, int, str, int, bool]] = []  # (-priority, order, url, depth, is_probe)
        pages_attempted = 1
        parsed: Set[str] = {canonical_key(root)}  # pages already read (a redirect can lead to one we have)
        all_text: List[str] = []
        about_text = ""

        def consume(page: FetchResult, depth: int) -> None:
            nonlocal about_text
            data = extract_from_html(page.text, page.url)
            result.pages_visited += 1
            result.page_log.append(f"{page.status_code} {page.url}")
            if data.has_password_form and not data.emails:
                result.note = (result.note + " Login form seen; not interacting.").strip()
            for e in data.emails:
                se = SiteEmail(e.email, e.original, e.origin, e.context, source_url=page.url)
                result.emails.append(se)
            for attr in ("business_name", "phone", "city", "state", "country", "address"):
                if not getattr(result, attr) and getattr(data, attr):
                    setattr(result, attr, getattr(data, attr))
            if data.text:
                all_text.append(data.text[:60_000])
                if depth == 0:
                    result.context_text = data.text[:1500]
                elif re.search(r"about|who-we|our-story", page.url, re.I) and not about_text:
                    about_text = data.text[:1000]
            if depth < self.options.max_depth:
                for link, anchor in data.links:
                    self._queue_link(link, anchor, depth + 1, root_host, visited, heap)

        # Homepage
        consume(first, 0)
        had_relevant_link = any(-h[0] >= 40 for h in heap)

        # If no contact-like link was found, probe the usual suspects (bounded, polite, robots-checked)
        if not had_relevant_link and self.options.max_depth >= 1:
            base = _origin(root)
            for i, path in enumerate(PROBE_PATHS):
                key = canonical_key(base + path)
                if key not in visited:
                    visited.add(key)
                    self._order_counter += 1
                    heapq.heappush(heap, (-90 + i, self._order_counter, base + path, 1, True))

        while heap and pages_attempted < self.options.max_pages:
            if self.should_stop():
                result.note = (result.note + " Stopped early on request.").strip()
                break
            _, _, url, depth, probe = heapq.heappop(heap)
            try:
                if not await self.robots.allowed(url):
                    result.pages_skipped += 1
                    result.page_log.append(f"robots.txt disallows {url}")
                    continue
            except FetchError:
                continue
            pages_attempted += 1
            try:
                page = await self.fetcher.fetch(url)
            except FetchError as exc:
                if not probe:
                    result.pages_skipped += 1
                    result.page_log.append(f"skipped {url}: {exc.message}")
                continue
            if page.status_code >= 400:
                if not probe:
                    result.pages_skipped += 1
                    result.page_log.append(f"skipped {url}: HTTP {page.status_code}")
                continue
            # a redirect may have taken us off-site; only parse it if scope allows
            final_host = registrable_host(urlsplit(page.url).hostname or "")
            if final_host != root_host and not self.options.follow_external:
                result.pages_skipped += 1
                result.page_log.append(f"skipped {url}: redirected off-site to {final_host}")
                continue
            fk = canonical_key(page.url)
            if fk in parsed:
                continue
            parsed.add(fk)
            consume(page, depth)

        if heap and pages_attempted >= self.options.max_pages:
            result.note = (result.note + f" Page limit ({self.options.max_pages}) reached.").strip()

        # ---- finish ---------------------------------------------------------
        if about_text:
            result.context_text = (result.context_text + " " + about_text).strip()
        corpus = " ".join(all_text).lower()
        if self.options.keywords:
            result.matched_keywords = [k for k in self.options.keywords if k.lower() in corpus]
            if self.options.keyword_filter and not result.matched_keywords:
                result.status = "skipped"
                result.error = None
                result.note = f"No keyword match ({', '.join(self.options.keywords)}) in {result.pages_visited} pages; emails discarded."
                result.emails = []
                return result
        result.emails = _dedupe_site_emails(result.emails)
        for em in result.emails:
            if CONTACT_URL_RE.search(em.source_url):
                result.contact_page_url = em.source_url
                break
        if not result.contact_page_url and result.emails:
            result.contact_page_url = result.emails[0].source_url
        result.status = "success"
        if not result.emails:
            result.note = (result.note + " No public emails found.").strip()
        return result

    # ----------------------------------------------------------------- helpers
    async def _fetch_homepage(self, start: str, result: SiteResult) -> Optional[FetchResult]:
        candidates = [start]
        if start.startswith("https://"):
            candidates.append("http://" + start[len("https://"):])  # some small sites have no TLS
        last_error: Optional[FetchError] = None
        for url in candidates:
            try:
                if not await self.robots.allowed(url):
                    result.status, result.error = "skipped", "Disallowed by robots.txt"
                    return None
                page = await self.fetcher.fetch(url)
            except FetchError as exc:
                last_error = exc
                if exc.kind in ("network", "timeout") and url is not candidates[-1]:
                    continue
                break
            if page.status_code >= 400:
                last_error = FetchError("status", f"HTTP {page.status_code}", page.status_code)
                if page.status_code in (401, 403, 429):
                    result.status = "skipped"
                    result.error = f"Access restricted (HTTP {page.status_code}); not bypassing."
                    return None
                break
            if page.url != url:
                try:
                    if not await self.robots.allowed(page.url):
                        result.status, result.error = "skipped", "Disallowed by robots.txt (after redirect)"
                        return None
                except FetchError:
                    pass
            return page
        result.status = "failed"
        result.error = last_error.message if last_error else "Could not fetch the homepage"
        if last_error and last_error.kind == "unsafe":
            result.status = "skipped"
        return None

    def _queue_link(self, link: str, anchor: str, depth: int, root_host: str, visited: Set[str], heap: list) -> None:
        try:
            p = urlsplit(link)
        except ValueError:
            return
        host = registrable_host(p.hostname or "")
        if host != root_host and not self.options.follow_external:
            return
        relevance = score_link(link, anchor)
        if should_skip_link(link, relevance):
            return
        clean = urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))
        key = canonical_key(clean)
        if key in visited:
            return
        visited.add(key)
        priority = relevance if relevance else max(1, 20 - p.path.count("/") * 3)
        self._order_counter += 1
        heapq.heappush(heap, (-priority, self._order_counter, clean, depth, False))


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _dedupe_site_emails(items: List[SiteEmail]) -> List[SiteEmail]:
    seen: Dict[str, SiteEmail] = {}
    for it in items:
        if it.email not in seen:
            seen[it.email] = it
    return list(seen.values())
