"""URL normalization and SSRF protection.

Every outgoing request is validated here: scheme, port, host, and *all* resolved IP addresses must be
public. The fetcher re-runs this validation for every redirect hop and connects to the validated IP
(DNS pinning), which closes the DNS-rebinding window between "check" and "connect".
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Awaitable, Callable, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import get_settings

Resolver = Callable[[str, int], Awaitable[List[str]]]

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "kubernetes.default.svc",
}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home", ".corp", ".localdomain")
ALLOWED_PORTS = {80, 443, 8080, 8443}
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref", "_ga", "yclid"}


class InvalidURLError(ValueError):
    """The text could not be turned into a usable http(s) URL."""


class UnsafeURLError(ValueError):
    """The URL points somewhere the crawler must never connect to (private network, metadata, ...)."""


_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_url(raw: str, *, default_scheme: str = "https") -> str:
    """Normalise user input ("Acme.com ", "http://x.com/a#frag") into a clean absolute URL.

    Raises InvalidURLError for anything that is not a plausible web address."""
    if raw is None:
        raise InvalidURLError("Empty URL")
    text = str(raw).strip().strip("\"'<>").strip()
    if not text:
        raise InvalidURLError("Empty URL")
    if len(text) > 2048:
        raise InvalidURLError("URL is too long")
    if any(c.isspace() for c in text) or any(ord(c) < 32 for c in text):
        raise InvalidURLError("URL contains whitespace or control characters")
    if "@" in text.split("/")[0] and "://" not in text:
        raise InvalidURLError("That looks like an email address, not a website")
    if "://" not in text:
        if text.startswith("//"):
            text = default_scheme + ":" + text
        elif re.match(r"^[a-z][a-z0-9+.-]*:", text, re.I) and not re.match(r"^[^/]+:\d+(/|$)", text):
            raise InvalidURLError("Only http and https URLs are supported")
        else:
            text = f"{default_scheme}://{text}"
    try:
        parts = urlsplit(text)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise InvalidURLError(f"Malformed URL: {exc}") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidURLError("Only http and https URLs are supported")
    if parts.username or parts.password:
        raise InvalidURLError("URLs with embedded credentials are not allowed")
    if not hostname:
        raise InvalidURLError("URL has no host name")
    try:
        host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidURLError("Host name is not valid") from exc
    host = host.rstrip(".")
    is_ip = _is_ip_literal(host)
    if not is_ip and host not in BLOCKED_HOSTNAMES and not _DOMAIN_RE.match(host):
        # Single-label hosts like "intranet" and junk like "foo..bar" are rejected here.
        if "." not in host:
            raise InvalidURLError(f"'{host}' is not a valid public domain name")
        raise InvalidURLError(f"'{host}' is not a valid domain name")
    netloc = f"[{host}]" if (is_ip and ":" in host) else host
    if port and not ((parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")])
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def is_public_ip(ip: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        elif addr.sixtofour is not None:
            addr = addr.sixtofour
        elif addr.teredo is not None:
            return False
    return bool(
        addr.is_global
        and not addr.is_multicast
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_private
        and not addr.is_reserved
        and not addr.is_unspecified
    )


async def default_resolver(host: str, port: int) -> List[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: List[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.append(ip)
    return seen


def is_fixture_netloc(host: str, port: Optional[int], scheme: str = "http") -> bool:
    """The only sanctioned exception: exact host:port pairs configured in TEST_FIXTURE_HOSTS."""
    allowed = get_settings().fixture_host_set
    if not allowed:
        return False
    eff_port = port or (443 if scheme == "https" else 80)
    return f"{host}:{eff_port}".lower() in allowed


async def validate_destination(url: str, resolver: Optional[Resolver] = None) -> List[str]:
    """Return the validated public IPs for ``url`` or raise UnsafeURLError / InvalidURLError."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError as exc:
        raise InvalidURLError(f"Malformed URL: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Scheme '{parts.scheme}' is not allowed")
    if not host:
        raise InvalidURLError("URL has no host name")
    eff_port = port or (443 if parts.scheme == "https" else 80)

    if is_fixture_netloc(host, eff_port, parts.scheme):
        return [host]  # explicit local test fixture, never enabled by default

    if eff_port not in ALLOWED_PORTS:
        raise UnsafeURLError(f"Port {eff_port} is not allowed")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURLError(f"Host '{host}' is not a public internet address")

    if _is_ip_literal(host):
        literal = host.strip("[]")
        if not is_public_ip(literal):
            raise UnsafeURLError(f"Address {literal} is private, loopback, link-local or reserved")
        return [literal]

    try:
        ips = await (resolver or default_resolver)(host, eff_port)
    except (socket.gaierror, OSError, UnicodeError) as exc:
        raise InvalidURLError(f"Could not resolve host '{host}'") from exc
    if not ips:
        raise InvalidURLError(f"Could not resolve host '{host}'")
    bad = [ip for ip in ips if not is_public_ip(ip)]
    if bad:  # reject if ANY record is private: stops mixed public/private rebinding tricks
        raise UnsafeURLError(f"Host '{host}' resolves to a non-public address ({bad[0]})")
    return ips


def registrable_host(host: str) -> str:
    """Host without a leading 'www.' - used for same-site comparisons."""
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    return registrable_host(urlsplit(a).hostname or "") == registrable_host(urlsplit(b).hostname or "")


def split_urls(text: str) -> Iterable[str]:
    for line in re.split(r"[\r\n,;\t ]+", text or ""):
        line = line.strip()
        if line:
            yield line
