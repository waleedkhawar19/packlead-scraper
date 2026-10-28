"""Free, non-intrusive email checks.

What this module does:   syntax, domain format, placeholder detection, role-account detection, MX lookup.
What it deliberately does NOT do: SMTP probing ("RCPT TO" tests) or claim a mailbox exists. A valid
syntax or an MX record only means the *domain* can receive mail; the specific mailbox is unverified.

Statuses
    Invalid Syntax   address is not syntactically valid
    Placeholder      obvious dummy address (example.com, yourname@..., etc.)
    Syntax Valid     syntax OK, DNS was not checked
    Domain MX Found  the domain publishes mail servers (mailbox itself NOT confirmed)
    No MX Found      the domain has no MX or A/AAAA record, or does not exist
    Unverified       DNS lookup failed/timed out, so nothing can be said either way
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from app.config import get_settings

STATUS_INVALID = "Invalid Syntax"
STATUS_PLACEHOLDER = "Placeholder"
STATUS_SYNTAX_OK = "Syntax Valid"
STATUS_MX = "Domain MX Found"
STATUS_NO_MX = "No MX Found"
STATUS_UNVERIFIED = "Unverified"
ALL_STATUSES = [STATUS_SYNTAX_OK, STATUS_MX, STATUS_NO_MX, STATUS_UNVERIFIED, STATUS_INVALID, STATUS_PLACEHOLDER]

ROLE_LOCALS = {
    "info", "sales", "contact", "support", "orders", "order", "admin", "office", "hello", "help",
    "service", "customerservice", "customer.service", "customer-service", "billing", "accounts",
    "accounting", "marketing", "team", "enquiries", "inquiries", "enquiry", "inquiry", "mail",
    "webmaster", "postmaster", "hr", "jobs", "careers", "press", "media", "purchasing", "quotes",
    "quote", "wholesale", "shipping", "returns", "feedback", "general", "reception", "hi", "care",
    "noreply", "no-reply", "donotreply", "do-not-reply",
}
NO_REPLY_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply", "no_reply"}

PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "example.edu", "test.com", "domain.com", "yourdomain.com",
    "yourcompany.com", "yoursite.com", "yourwebsite.com", "mydomain.com", "mysite.com", "email.com",
    "company.com", "website.com", "site.com", "sample.com", "demo.com", "localhost", "invalid.com",
    "sentry.io", "sentry.wixpress.com", "sentry-next.wixpress.com", "wixpress.com", "godaddy.com.test",
}
PLACEHOLDER_TLDS = {"invalid", "localhost", "local", "internal"}  # .test/.example stay allowed for fixtures
PLACEHOLDER_LOCALS = {
    "you", "your", "yourname", "your.name", "youremail", "your-email", "your.email", "yourmail", "name",
    "email", "username", "user", "test", "testing", "sample", "someone", "somebody", "example", "demo",
    "firstname", "lastname", "firstname.lastname", "first.last", "name.surname", "john.doe", "jane.doe",
    "john.smith", "email.address", "emailaddress", "xxx", "xxxx", "abc", "foo", "bar", "johndoe", "janedoe",
}

# Things that look like emails to a regex but are file names ("logo@2x.png").
FILE_EXTENSION_TLDS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico", "tif", "tiff", "css", "js", "mjs", "map",
    "woff", "woff2", "ttf", "eot", "otf", "mp4", "mp3", "webm", "avif", "pdf", "zip", "html", "htm",
    "php", "json", "xml", "txt",
}

_LOCAL_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def check_syntax(email: str) -> Tuple[bool, str]:
    """Pragmatic RFC 5322 subset. Returns (ok, reason_if_not)."""
    if not email or "@" not in email:
        return False, "missing @"
    if email.count("@") != 1:
        return False, "more than one @"
    local, domain = email.split("@")
    if not local or len(local) > 64:
        return False, "local part empty or longer than 64 characters"
    if len(email) > 254:
        return False, "longer than 254 characters"
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return False, "local part has a leading, trailing or doubled dot"
    if not _LOCAL_RE.match(local):
        return False, "local part has invalid characters"
    ok, why = check_domain_format(domain)
    return (ok, why)


def check_domain_format(domain: str) -> Tuple[bool, str]:
    if not domain or len(domain) > 253:
        return False, "domain empty or too long"
    labels = domain.split(".")
    if len(labels) < 2:
        return False, "domain has no TLD"
    if not all(_LABEL_RE.match(label) for label in labels):
        return False, "domain has an invalid label"
    tld = labels[-1]
    if not re.fullmatch(r"[A-Za-z]{2,24}|xn--[A-Za-z0-9-]{2,59}", tld):
        return False, "invalid top-level domain"
    return True, ""


def is_placeholder(email: str) -> bool:
    email = email.lower()
    if "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    if domain in PLACEHOLDER_DOMAINS or domain.endswith(".example.com") or domain.endswith(".wixpress.com"):
        return True
    if domain.rsplit(".", 1)[-1] in PLACEHOLDER_TLDS:
        return True
    if local in PLACEHOLDER_LOCALS:
        return True
    if re.fullmatch(r"(x+|\*+|\.+|_+)", local):
        return True
    return False


def looks_like_filename(email: str) -> bool:
    return email.rsplit(".", 1)[-1].lower() in FILE_EXTENSION_TLDS


def is_role_based(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return local in ROLE_LOCALS or local.replace(".", "").replace("_", "") in ROLE_LOCALS


@dataclass
class ValidationResult:
    email: str
    status: str
    detail: str
    is_role_based: bool = False
    is_placeholder: bool = False
    mx_hosts: Optional[List[str]] = None


MXLookup = Callable[[str], Awaitable[Tuple[str, List[str], str]]]
# returns (outcome, hosts, message); outcome in {"mx", "a", "none", "error"}


async def dns_mx_lookup(domain: str) -> Tuple[str, List[str], str]:
    """Look up MX records (falling back to A/AAAA as RFC 5321 specifies)."""
    import dns.asyncresolver
    import dns.exception
    import dns.resolver

    timeout = get_settings().dns_timeout
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        answer = await resolver.resolve(domain, "MX")
        hosts = [str(r.exchange).rstrip(".") for r in sorted(answer, key=lambda r: r.preference)]
        # RFC 7505 "null MX": a single '.' means the domain accepts no mail
        if hosts == [""] or hosts == ["."]:
            return "none", [], "domain publishes a null MX (accepts no mail)"
        return "mx", hosts, ""
    except dns.resolver.NXDOMAIN:
        return "none", [], "domain does not exist (NXDOMAIN)"
    except dns.resolver.NoAnswer:
        pass  # fall back to address records below
    except (dns.exception.Timeout, dns.resolver.NoNameservers, OSError) as exc:
        return "error", [], f"DNS lookup failed: {type(exc).__name__}"
    except dns.exception.DNSException as exc:
        return "error", [], f"DNS lookup failed: {type(exc).__name__}"
    for rtype in ("A", "AAAA"):
        try:
            await resolver.resolve(domain, rtype)
            return "a", [domain], ""
        except dns.resolver.NoAnswer:
            continue
        except dns.resolver.NXDOMAIN:
            return "none", [], "domain does not exist (NXDOMAIN)"
        except (dns.exception.DNSException, OSError) as exc:
            return "error", [], f"DNS lookup failed: {type(exc).__name__}"
    return "none", [], "domain has no MX, A or AAAA records"


class EmailValidator:
    """Caches DNS results per domain so 1,000 leads on 300 domains do 300 lookups."""

    def __init__(self, lookup: Optional[MXLookup] = None, concurrency: int = 10):
        self._lookup = lookup or dns_mx_lookup
        self._cache: Dict[str, Tuple[str, List[str], str]] = {}
        self._sem = asyncio.Semaphore(concurrency)

    async def _mx(self, domain: str) -> Tuple[str, List[str], str]:
        if domain not in self._cache:
            async with self._sem:
                if domain not in self._cache:
                    try:
                        self._cache[domain] = await self._lookup(domain)
                    except Exception as exc:  # noqa: BLE001
                        self._cache[domain] = ("error", [], f"DNS lookup failed: {type(exc).__name__}")
        return self._cache[domain]

    def validate_offline(self, email: str) -> ValidationResult:
        email = (email or "").strip().lower()
        ok, why = check_syntax(email)
        if not ok:
            return ValidationResult(email, STATUS_INVALID, f"Invalid syntax: {why}")
        role = is_role_based(email)
        if is_placeholder(email):
            return ValidationResult(email, STATUS_PLACEHOLDER, "Looks like a placeholder/dummy address", role, True)
        detail = "Syntax is valid. DNS was not checked; mailbox existence is not confirmed."
        return ValidationResult(email, STATUS_SYNTAX_OK, detail, role)

    async def validate(self, email: str, check_mx: bool = True) -> ValidationResult:
        result = self.validate_offline(email)
        if result.status != STATUS_SYNTAX_OK or not check_mx:
            return result
        domain = result.email.split("@", 1)[1]
        outcome, hosts, message = await self._mx(domain)
        result.mx_hosts = hosts
        if outcome == "mx":
            result.status = STATUS_MX
            shown = ", ".join(hosts[:3])
            result.detail = f"Domain publishes mail servers ({shown}). This does NOT confirm the mailbox exists."
        elif outcome == "a":
            result.status = STATUS_MX
            result.detail = "Domain has no MX record but has an address record (mail may be delivered to the host). Mailbox not confirmed."
        elif outcome == "none":
            result.status = STATUS_NO_MX
            result.detail = f"No mail servers found: {message}."
        else:
            result.status = STATUS_UNVERIFIED
            result.detail = f"{message}. Nothing could be concluded about this domain."
        return result

    async def validate_many(self, emails: Iterable[str], check_mx: bool = True) -> Dict[str, ValidationResult]:
        unique = list(dict.fromkeys(e.lower() for e in emails))
        results = await asyncio.gather(*(self.validate(e, check_mx) for e in unique))
        return {r.email: r for r in results}
