"""Find publicly displayed emails (and a little business context) in text and HTML.

HTML is parsed with BeautifulSoup - visible text, ``mailto:`` links, Cloudflare-obfuscated
addresses and JSON-LD are all inspected - and then a regular expression is applied to the *text*,
not to raw markup, so scripts, CSS and attributes do not generate junk matches.
"""
from __future__ import annotations

import html as htmllib
from collections import deque
import json
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup, Comment

from app.services.email_validator import (
    check_syntax,
    is_placeholder,
    looks_like_filename,
)

EMAIL_RE = re.compile(
    r"(?<![\w.+%-])[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}(?![\w-])"
)
_OBF_AT = re.compile(r"\s*[\[\(\{<]\s*(?:at|AT|@)\s*[\]\)\}>]\s*")
_OBF_DOT = re.compile(r"\s*[\[\(\{<]\s*(?:dot|DOT|\.)\s*[\]\)\}>]\s*")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'\)\]\}]+", re.I)
PHONE_RE = re.compile(r"(?<![\d.])(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?([2-9]\d{2})[\s.-]?(\d{4})(?![\d])")
CITY_STATE_ZIP_RE = re.compile(r"([A-Z][A-Za-z.'\- ]{1,40}),\s*([A-Z]{2})\.?\s+(\d{5})(?:-\d{4})?\b")

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
_GENERIC_TITLE_WORDS = re.compile(
    r"^(home|homepage|welcome|contact( us)?|about( us)?|index|main|official site|official website|"
    r"products?|shop|store|services?|locations?|menu|login|sign in|404.*|just another.*)$",
    re.I,
)


@dataclass
class FoundEmail:
    email: str  # normalized lowercase
    original: str  # exactly as displayed
    origin: str = "text"  # text | mailto | cfemail | jsonld | obfuscated
    context: str = ""  # short surrounding snippet


@dataclass
class HtmlExtraction:
    emails: List[FoundEmail] = field(default_factory=list)
    links: List[Tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)
    title: str = ""
    business_name: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    address: str = ""
    text: str = ""
    meta_description: str = ""
    has_password_form: bool = False


# ---------------------------------------------------------------------------- email helpers
def normalize_email(raw: str) -> str:
    """Lowercase, remove ``mailto:``/query/percent-encoding/trailing punctuation."""
    s = htmllib.unescape(str(raw)).strip()
    s = unquote(s)
    if s.lower().startswith("mailto:"):
        s = s[7:]
    s = s.split("?", 1)[0].strip().strip("<>\"' \t\r\n;,:()[]")
    return s.rstrip(".").lower()


def _acceptable(email: str) -> bool:
    ok, _ = check_syntax(email)
    return ok and not looks_like_filename(email) and not is_placeholder(email)


def deobfuscate(text: str) -> str:
    """Turn 'info [at] acme [dot] com' into 'info@acme.com'. Only bracketed forms are handled, so
    ordinary prose containing the word 'at' is never altered."""
    if "[" not in text and "(" not in text and "{" not in text and "<" not in text:
        return text
    return _OBF_DOT.sub(".", _OBF_AT.sub("@", text))


def decode_cfemail(encoded: str) -> Optional[str]:
    """Decode Cloudflare's ``data-cfemail`` / ``/cdn-cgi/l/email-protection#...`` values."""
    try:
        data = bytes.fromhex(encoded)
        key = data[0]
        return "".join(chr(b ^ key) for b in data[1:])
    except (ValueError, IndexError):
        return None


def extract_emails_from_text(text: str, *, origin: str = "text", context_chars: int = 70) -> List[FoundEmail]:
    """Regex scan of plain text. Deduplicates within the text; keeps first-seen order."""
    if not text:
        return []
    cleaned = deobfuscate(htmllib.unescape(text))
    out: List[FoundEmail] = []
    seen: Set[str] = set()
    for m in EMAIL_RE.finditer(cleaned):
        raw = m.group(0)
        norm = normalize_email(raw)
        if norm in seen or not _acceptable(norm):
            continue
        seen.add(norm)
        start, end = max(0, m.start() - context_chars), min(len(cleaned), m.end() + context_chars)
        out.append(FoundEmail(norm, raw, origin, " ".join(cleaned[start:end].split())))
    return out


def extract_urls_from_text(text: str) -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?'\"")
        if u.lower().startswith("www."):
            u = "https://" + u
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def dedupe_emails(items: Iterable[FoundEmail]) -> List[FoundEmail]:
    """Remove duplicates (case-insensitive) while preserving the first display value."""
    seen: Dict[str, FoundEmail] = {}
    for item in items:
        seen.setdefault(item.email.lower(), item)
    return list(seen.values())


# ---------------------------------------------------------------------------- HTML
def _soup(markup: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception:  # noqa: BLE001
        return BeautifulSoup(markup, "html.parser")


def _iter_jsonld(soup: BeautifulSoup) -> Iterable[dict]:
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        stack = deque([data])
        while stack:
            node = stack.popleft()  # FIFO keeps listing order
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                for key in ("@graph", "itemListElement", "item", "mainEntity", "member", "employee", "contactPoint"):
                    if key in node:
                        stack.append(node[key])


def _jsonld_types(node: dict) -> List[str]:
    t = node.get("@type", [])
    return [t] if isinstance(t, str) else [str(x) for x in t]


def clean_business_name(name: str) -> str:
    name = " ".join(htmllib.unescape(name or "").split())
    return name[:200] if 1 < len(name) else ""


def _name_from_title(title: str) -> str:
    parts = [p.strip() for p in re.split(r"\s+[|–—·•:-]\s+|\s*\|\s*", title) if p.strip()]
    for p in parts:
        if not _GENERIC_TITLE_WORDS.match(p) and 1 < len(p) <= 80:
            return p
    return ""


def extract_from_html(markup: str, base_url: str = "") -> HtmlExtraction:
    """Parse one HTML page. Never raises on bad markup."""
    result = HtmlExtraction()
    if not markup:
        return result
    soup = _soup(markup)
    found: List[FoundEmail] = []

    # 1. mailto: links (and the anchor text, which may be a different display value)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        label = " ".join(a.get_text(" ").split())
        if href.lower().startswith("mailto:"):
            for chunk in re.split(r"[,;]", unquote(href[7:].split("?", 1)[0])):
                norm = normalize_email(chunk)
                if _acceptable(norm):
                    found.append(FoundEmail(norm, label if "@" in label else chunk.strip(), "mailto", label[:140]))
        elif "/cdn-cgi/l/email-protection#" in href:
            decoded = decode_cfemail(href.split("#", 1)[1])
            if decoded and _acceptable(normalize_email(decoded)):
                found.append(FoundEmail(normalize_email(decoded), decoded, "cfemail", label[:140]))
        try:
            absolute = urljoin(base_url, href) if base_url else href
        except ValueError:
            continue
        if absolute.lower().startswith(("http://", "https://")):
            result.links.append((absolute, label[:120]))

    # 2. Cloudflare email protection elements
    for el in soup.find_all(attrs={"data-cfemail": True}):
        decoded = decode_cfemail(el["data-cfemail"])
        if decoded and _acceptable(normalize_email(decoded)):
            found.append(FoundEmail(normalize_email(decoded), decoded, "cfemail", ""))

    # 3. JSON-LD structured data (names, phones, addresses and emails the site publishes itself)
    for node in _iter_jsonld(soup):
        types = _jsonld_types(node)
        email = node.get("email")
        if isinstance(email, str):
            for e in extract_emails_from_text(email, origin="jsonld"):
                found.append(e)
        if any(t in ("Organization", "LocalBusiness", "Corporation", "Store", "OnlineStore", "Manufacturer",
                     "Restaurant", "FoodEstablishment", "ProfessionalService", "WholesaleStore") or t.endswith("Business") or t.endswith("Store")
               for t in types):
            if not result.business_name and isinstance(node.get("name"), str):
                result.business_name = clean_business_name(node["name"])
            tel = node.get("telephone")
            if isinstance(tel, str) and not result.phone:
                result.phone = tel.strip()[:40]
            addr = node.get("address")
            if isinstance(addr, dict):
                _apply_address(result, addr)

    # 4. Meta information
    if soup.title and soup.title.string:
        result.title = " ".join(soup.title.string.split())[:200]
    for key in ("og:site_name", "application-name"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content") and not result.business_name:
            result.business_name = clean_business_name(tag["content"])
    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content"):
        result.meta_description = " ".join(desc["content"].split())[:300]
    if not result.business_name and result.title:
        result.business_name = clean_business_name(_name_from_title(result.title))

    # 5. tel: links
    if not result.phone:
        for a in soup.find_all("a", href=re.compile(r"^tel:", re.I)):
            digits = re.sub(r"[^\d+]", "", unquote(a["href"][4:]))
            if 10 <= len(digits.lstrip("+")) <= 15:
                result.phone = unquote(a["href"][4:]).strip()[:40]
                break

    result.has_password_form = bool(soup.find("input", attrs={"type": "password"}))

    # 6. Visible text (scripts/styles/comments removed)
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    text = " ".join(soup.get_text(" ").split())
    result.text = text
    found.extend(extract_emails_from_text(text, origin="text"))

    if not result.phone:
        m = PHONE_RE.search(text)
        if m:
            result.phone = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
    if not result.state:
        for m in CITY_STATE_ZIP_RE.finditer(text):
            if m.group(2) in US_STATES:
                result.city = m.group(1).strip().split("  ")[-1].split(" at ")[-1].strip()[:80]
                result.state = US_STATES[m.group(2)]
                result.country = "United States"
                result.address = " ".join(m.group(0).split())
                break

    result.emails = dedupe_emails(found)
    return result


def _apply_address(result: HtmlExtraction, addr: dict) -> None:
    street = addr.get("streetAddress") or ""
    city = addr.get("addressLocality") or ""
    region = addr.get("addressRegion") or ""
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    if isinstance(city, str) and city and not result.city:
        result.city = city.strip()[:80]
    if isinstance(region, str) and region and not result.state:
        r = region.strip()
        result.state = US_STATES.get(r.upper(), r)[:60]
    if isinstance(country, str) and country and not result.country:
        c = country.strip()
        result.country = "United States" if c.upper() in ("US", "USA", "UNITED STATES") else c[:80]
    if not result.address:
        bits = [x for x in (street, city, region, addr.get("postalCode", "")) if isinstance(x, str) and x]
        result.address = ", ".join(bits)[:300]
