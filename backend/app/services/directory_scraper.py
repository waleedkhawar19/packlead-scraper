"""Public business-directory scraping framework.

Architecture
    DirectoryAdapter      abstract parser for ONE directory layout (can_handle / parse / next_page)
    JsonLdAdapter         reads schema.org LocalBusiness/Organization data many directories publish
    GenericAdapter        heuristic "business card" parser for ordinary accessible listing pages
    ADAPTERS              registry; the first adapter whose ``can_handle`` returns True wins

To support a specific directory, subclass ``DirectoryAdapter``, implement the three methods, and
append an instance to ``ADAPTERS`` *before* ``GenericAdapter`` (see README, "Writing an adapter").

There is no claim of universal compatibility: layouts differ, and the generic parser is a best
effort. Directories that require login, CAPTCHA solving, payment, or disallow bots via robots.txt are
skipped with an explanation - this module never tries to get around those controls."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from app.config import Settings, get_settings
from app.services.email_extractor import (
    CITY_STATE_ZIP_RE,
    PHONE_RE,
    US_STATES,
    _apply_address,
    _iter_jsonld,
    _jsonld_types,
    _soup,
    clean_business_name,
    extract_emails_from_text,
    extract_from_html,
    normalize_email,
)
from app.services.email_validator import is_placeholder
from app.services.website_crawler import RobotsPolicy
from app.utils.http import FetchError, SafeFetcher
from app.utils.url_safety import InvalidURLError, normalize_url, registrable_host

SOCIAL_HOSTS = ("facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com", "youtube.com", "pinterest.com", "tiktok.com", "yelp.com", "google.com", "goo.gl", "apple.com")
BLOCK_MARKERS = (
    "g-recaptcha", "h-captcha", "hcaptcha", "cf-challenge", "cf-turnstile", "verify you are human",
    "are you a robot", "unusual traffic", "attention required! | cloudflare", "access denied",
)
NEXT_TEXT_RE = re.compile(r"^\s*(next(\s+page)?|more|older|»|›|>|→|next\s*[»›>])\s*$", re.I)


@dataclass
class DirectoryRecord:
    business_name: str = ""
    website: str = ""
    emails: List[str] = field(default_factory=list)
    original_emails: Dict[str, str] = field(default_factory=dict)
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    category: str = ""
    source_url: str = ""
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def key(self) -> str:
        site = registrable_host(urlsplit(self.website).hostname or "") if self.website else ""
        return (site or self.business_name.lower() or ",".join(self.emails)).strip()


@dataclass
class DirectoryOptions:
    max_pages: int = 5
    delay: float = 1.5
    crawl_websites: bool = False  # follow each listing's own website to look for emails
    max_sites: int = 25
    respect_robots: bool = True


@dataclass
class DirectoryResult:
    start_url: str
    status: str = "pending"  # success | failed | skipped
    error: Optional[str] = None
    note: str = ""
    adapter: str = ""
    pages_visited: int = 0
    pages_skipped: int = 0
    records: List[DirectoryRecord] = field(default_factory=list)


# ------------------------------------------------------------------------- adapters
class DirectoryAdapter(ABC):
    name = "base"

    @abstractmethod
    def can_handle(self, url: str, soup: BeautifulSoup) -> bool: ...

    @abstractmethod
    def parse(self, soup: BeautifulSoup, page_url: str) -> List[DirectoryRecord]: ...

    def next_page(self, soup: BeautifulSoup, page_url: str) -> Optional[str]:
        return default_next_page(soup, page_url)


def default_next_page(soup: BeautifulSoup, page_url: str) -> Optional[str]:
    link = soup.find("link", rel=lambda v: v and "next" in (v if isinstance(v, list) else [v]))
    if link and link.get("href"):
        return urljoin(page_url, link["href"])
    for a in soup.find_all("a", href=True):
        rel = a.get("rel") or []
        label = " ".join(a.get_text(" ").split())
        aria = (a.get("aria-label") or "").lower()
        if "next" in rel or NEXT_TEXT_RE.match(label) or aria.startswith("next"):
            href = a["href"].strip()
            if href and not href.startswith(("#", "javascript:")):
                return urljoin(page_url, href)
    return None


def _host(url: str) -> str:
    return registrable_host(urlsplit(url).hostname or "")


def _clean_site(url: str, directory_url: str) -> str:
    try:
        n = normalize_url(url)
    except InvalidURLError:
        return ""
    host = _host(n)
    if _host(directory_url) == host or any(host == s or host.endswith("." + s) for s in SOCIAL_HOSTS):
        return ""
    p = urlsplit(n)
    return f"{p.scheme}://{p.netloc}/"


class JsonLdAdapter(DirectoryAdapter):
    name = "schema.org JSON-LD"
    BUSINESS_TYPES = ("LocalBusiness", "Organization", "Store", "Corporation", "Restaurant", "FoodEstablishment", "ProfessionalService")

    def _nodes(self, soup: BeautifulSoup) -> List[dict]:
        out = []
        for node in _iter_jsonld(soup):
            types = _jsonld_types(node)
            if any(t in self.BUSINESS_TYPES or t.endswith("Business") or t.endswith("Store") for t in types) and node.get("name"):
                out.append(node)
        return out

    def can_handle(self, url: str, soup: BeautifulSoup) -> bool:
        return len(self._nodes(soup)) >= 2  # a single node is usually the directory's own organisation

    def parse(self, soup: BeautifulSoup, page_url: str) -> List[DirectoryRecord]:
        records = []
        for node in self._nodes(soup):
            rec = DirectoryRecord(business_name=clean_business_name(str(node.get("name"))), source_url=page_url)
            site = node.get("url") or node.get("sameAs")
            if isinstance(site, list):
                site = next((s for s in site if isinstance(s, str)), "")
            if isinstance(site, str):
                rec.website = _clean_site(site, page_url)
            email = node.get("email")
            if isinstance(email, str):
                for e in extract_emails_from_text(email):
                    rec.emails.append(e.email)
                    rec.original_emails[e.email] = e.original
            tel = node.get("telephone")
            rec.phone = tel.strip()[:40] if isinstance(tel, str) else ""
            holder = type("H", (), {"city": "", "state": "", "country": "", "address": ""})()
            if isinstance(node.get("address"), dict):
                _apply_address(holder, node["address"])  # type: ignore[arg-type]
            rec.city, rec.state, rec.country, rec.address = holder.city, holder.state, holder.country, holder.address
            records.append(rec)
        return records


class GenericAdapter(DirectoryAdapter):
    """Finds repeated "cards" by locating contact anchors (mailto / website / tel) and climbing to the
    smallest ancestor that contains exactly one business."""

    name = "generic listing parser"
    WEBSITE_LABEL_RE = re.compile(r"web\s*site|visit|homepage|www\.|\.com|\.net|\.org", re.I)

    def can_handle(self, url: str, soup: BeautifulSoup) -> bool:
        return True

    def _anchors(self, soup: BeautifulSoup, page_url: str) -> List[Tag]:
        anchors = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith(("mailto:", "tel:")):
                anchors.append(a)
            elif href.startswith("http") and _clean_site(href, page_url) and self.WEBSITE_LABEL_RE.search(a.get_text(" ") + " " + " ".join(a.get("class", []))):
                anchors.append(a)
        return anchors

    @staticmethod
    def _card_for(anchor: Tag, all_anchors_in: Callable[[Tag], int]) -> Tag:
        node: Tag = anchor
        best = anchor.parent if isinstance(anchor.parent, Tag) else anchor
        for _ in range(7):
            parent = node.parent
            if not isinstance(parent, Tag) or parent.name in ("body", "html", "[document]"):
                break
            # stop climbing when the ancestor holds more than one business (>=2 distinct mailto targets/websites)
            if all_anchors_in(parent) > 1:
                break
            best = parent
            node = parent
        return best

    def parse(self, soup: BeautifulSoup, page_url: str) -> List[DirectoryRecord]:
        anchors = self._anchors(soup, page_url)
        if not anchors:
            return []

        def business_keys(tag: Tag) -> int:
            keys = set()
            for a in tag.find_all("a", href=True):
                h = a["href"].strip()
                low = h.lower()
                if low.startswith("mailto:"):
                    keys.add("m:" + normalize_email(h))
                elif low.startswith("http") and _clean_site(h, page_url) and self.WEBSITE_LABEL_RE.search(a.get_text(" ") + " " + " ".join(a.get("class", []))):
                    keys.add("w:" + _clean_site(h, page_url))
            return len(keys)

        seen_cards: Set[int] = set()
        records: List[DirectoryRecord] = []
        for a in anchors:
            card = self._card_for(a, business_keys)
            if id(card) in seen_cards:
                continue
            seen_cards.add(id(card))
            rec = self._record(card, page_url)
            if rec and (rec.emails or rec.website or rec.phone):
                records.append(rec)
        return records

    def _record(self, card: Tag, page_url: str) -> Optional[DirectoryRecord]:
        rec = DirectoryRecord(source_url=page_url)
        for a in card.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            if low.startswith("mailto:"):
                for chunk in re.split(r"[,;]", href[7:].split("?", 1)[0]):
                    n = normalize_email(chunk)
                    if n and "@" in n and not is_placeholder(n) and n not in rec.emails:
                        rec.emails.append(n)
                        rec.original_emails[n] = chunk.strip()
            elif low.startswith("tel:") and not rec.phone:
                rec.phone = href[4:].strip()[:40]
            elif low.startswith("http") and not rec.website:
                site = _clean_site(href, page_url)
                if site and self.WEBSITE_LABEL_RE.search(a.get_text(" ") + " " + " ".join(a.get("class", []))):
                    rec.website = site
        text = " ".join(card.get_text(" ").split())
        for e in extract_emails_from_text(text):
            if e.email not in rec.emails:
                rec.emails.append(e.email)
                rec.original_emails[e.email] = e.original
        if not rec.phone:
            m = PHONE_RE.search(text)
            if m:
                rec.phone = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
        heading = card.find(["h1", "h2", "h3", "h4", "h5"])
        if heading:
            rec.business_name = clean_business_name(heading.get_text(" "))
        else:
            named = card.find(class_=re.compile(r"(^|[-_ ])(name|title|business|company)([-_ ]|$)", re.I))
            if named:
                rec.business_name = clean_business_name(named.get_text(" "))
        addr_el = card.find(class_=re.compile(r"addr", re.I)) or card.find("address")
        addr_text = " ".join(addr_el.get_text(" ").split()) if addr_el else text
        if addr_el:
            rec.address = addr_text[:300]
        for m in CITY_STATE_ZIP_RE.finditer(addr_text):
            if m.group(2) in US_STATES:
                rec.city = m.group(1).strip().split("  ")[-1][:80]
                rec.state = US_STATES[m.group(2)]
                rec.country = "United States"
                rec.address = rec.address or " ".join(m.group(0).split())
                break
        cat = card.find(class_=re.compile(r"categor", re.I))
        if cat:
            rec.category = " ".join(cat.get_text(" ").split())[:100]
        return rec


ADAPTERS: List[DirectoryAdapter] = [JsonLdAdapter(), GenericAdapter()]


# ------------------------------------------------------------------------- scraper
def looks_blocked(text: str) -> Optional[str]:
    low = text.lower()
    for marker in BLOCK_MARKERS:
        if marker in low:
            return f"The page shows an anti-bot/CAPTCHA challenge ('{marker}'). Automated access is not bypassed."
    return None


class DirectoryScraper:
    def __init__(self, fetcher: SafeFetcher, options: Optional[DirectoryOptions] = None, *, settings: Optional[Settings] = None,
                 should_stop: Optional[Callable[[], bool]] = None, adapters: Optional[List[DirectoryAdapter]] = None):
        self.settings = settings or get_settings()
        self.fetcher = fetcher
        self.options = options or DirectoryOptions()
        self.options.max_pages = max(1, min(self.options.max_pages, self.settings.max_pages_limit))
        self.should_stop = should_stop or (lambda: False)
        self.adapters = adapters or ADAPTERS
        self.robots = RobotsPolicy(fetcher, self.settings, self.options.respect_robots and self.settings.respect_robots_txt)

    async def scrape(self, input_url: str) -> DirectoryResult:
        result = DirectoryResult(start_url=input_url)
        try:
            url = normalize_url(input_url)
        except InvalidURLError as exc:
            result.status, result.error = "failed", f"Invalid URL: {exc}"
            return result
        result.start_url = url
        seen_urls: Set[str] = set()
        seen_records: Set[str] = set()
        current: Optional[str] = url
        while current and result.pages_visited < self.options.max_pages:
            if self.should_stop():
                result.note += " Stopped early on request."
                break
            norm = urlunsplit(urlsplit(current)._replace(fragment=""))
            if norm in seen_urls:
                break
            seen_urls.add(norm)
            try:
                if not await self.robots.allowed(norm):
                    if result.pages_visited == 0:
                        result.status, result.error = "skipped", "robots.txt does not allow automated access to this directory."
                        return result
                    result.pages_skipped += 1
                    result.note += " Stopped: robots.txt disallows further pages."
                    break
                page = await self.fetcher.fetch(norm, delay=self.options.delay)
            except FetchError as exc:
                if result.pages_visited == 0:
                    result.status = "skipped" if exc.kind == "unsafe" else "failed"
                    result.error = exc.message
                    return result
                result.pages_skipped += 1
                result.note += f" Stopped at page {result.pages_visited + 1}: {exc.message}."
                break
            if page.status_code in (401, 402, 403, 407, 429):
                reason = {401: "requires login", 402: "requires payment", 403: "blocks automated access (HTTP 403)", 407: "requires proxy auth", 429: "rate-limited the crawler (HTTP 429)"}[page.status_code]
                if result.pages_visited == 0:
                    result.status, result.error = "skipped", f"Directory {reason}; skipped without trying to bypass."
                    return result
                result.pages_skipped += 1
                result.note += f" Stopped: directory {reason}."
                break
            if page.status_code >= 400:
                if result.pages_visited == 0:
                    result.status, result.error = "failed", f"HTTP {page.status_code}"
                    return result
                result.pages_skipped += 1
                break
            blocked = looks_blocked(page.text)
            soup = _soup(page.text)
            if blocked:
                if result.pages_visited == 0:
                    result.status, result.error = "skipped", blocked
                    return result
                result.note += f" Stopped: {blocked}"
                break
            if soup.find("input", attrs={"type": "password"}) and result.pages_visited == 0:
                result.status = "skipped"
                result.error = "The page asks for a login. Login-only directories are not scraped."
                return result

            adapter = next((a for a in self.adapters if a.can_handle(page.url, soup)), self.adapters[-1])
            result.adapter = adapter.name
            result.pages_visited += 1
            parsed = adapter.parse(soup, page.url)
            if not parsed:  # fall back to the page's own contact details
                data = extract_from_html(page.text, page.url)
                if data.emails:
                    rec = DirectoryRecord(business_name=data.business_name, phone=data.phone, city=data.city, state=data.state,
                                          country=data.country, address=data.address, source_url=page.url)
                    for e in data.emails:
                        rec.emails.append(e.email)
                        rec.original_emails[e.email] = e.original
                    parsed = [rec]
            new = 0
            for rec in parsed:
                k = rec.key()
                if k and k not in seen_records:
                    seen_records.add(k)
                    result.records.append(rec)
                    new += 1
            if new == 0 and result.pages_visited > 1:
                result.note += " Stopped: page produced no new businesses."
                break
            current = adapter.next_page(soup, page.url) or _increment_page_param(page.url) if new else None
            if current and _host(current) != _host(url):
                current = None  # never wander off to another website via pagination

        if result.pages_visited >= self.options.max_pages and current:
            result.note += f" Page limit ({self.options.max_pages}) reached."
        result.status = "success"
        if not result.records:
            result.note += " No businesses could be parsed from this page layout; a custom adapter may be needed."
        result.note = result.note.strip()
        return result


def _increment_page_param(url: str) -> Optional[str]:
    p = urlsplit(url)
    params = parse_qsl(p.query, keep_blank_values=True)
    for i, (k, v) in enumerate(params):
        if k.lower() in ("page", "p", "pg", "pagenum", "paged") and v.isdigit():
            params[i] = (k, str(int(v) + 1))
            return urlunsplit(p._replace(query=urlencode(params)))
    return None
