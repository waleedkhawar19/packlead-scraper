import pytest

from app.utils.url_safety import InvalidURLError, UnsafeURLError, is_public_ip, normalize_url, validate_destination
from tests.conftest import PUBLIC_IP, public_resolver


# ------------------------------------------------------------------ normalisation / malformed URLs
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Acme.com ", "https://acme.com/"),
        ("http://Acme.com/About#team", "http://acme.com/About"),
        ("https://acme.com/?utm_source=x&id=7&fbclid=abc", "https://acme.com/?id=7"),
        ("//acme.com/x", "https://acme.com/x"),
        ("https://acme.com:443/", "https://acme.com/"),
        ("https://acme.com:8443/", "https://acme.com:8443/"),
        ("bücher.de", "https://xn--bcher-kva.de/"),
        ("www.acme.co.uk/contact", "https://www.acme.co.uk/contact"),
    ],
)
def test_normalize_valid(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", None, "not a url", "ftp://acme.com", "javascript:alert(1)", "http://", "info@acme.com", "http://user:pw@acme.com", "intranet",
     "http://exa mple.com", "foo..bar.com", "x" * 3000, "file:///etc/passwd", "mailto:a@b.com", "http://-bad-.com"],
)
def test_normalize_rejects_malformed(raw):
    with pytest.raises(InvalidURLError):
        normalize_url(raw)


# ------------------------------------------------------------------ SSRF
@pytest.mark.parametrize(
    "ip,public",
    [
        ("93.184.216.34", True), ("8.8.8.8", True), ("2606:4700:4700::1111", True),
        ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False), ("172.31.255.255", False), ("192.168.0.10", False),
        ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False), ("240.0.0.1", False),
        ("::1", False), ("fe80::1", False), ("fc00::1", False), ("::ffff:127.0.0.1", False), ("::ffff:10.0.0.1", False), ("not-an-ip", False),
    ],
)
def test_is_public_ip(ip, public):
    assert is_public_ip(ip) is public


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/", "http://127.0.0.1/", "http://127.0.0.1:8100/", "http://10.0.0.5/admin", "http://192.168.1.1/", "http://172.16.5.5/",
        "http://169.254.169.254/latest/meta-data/", "http://metadata.google.internal/computeMetadata/v1/", "http://[::1]/", "http://0.0.0.0/",
        "http://100.64.0.1/", "http://printer.local/", "http://db.internal/", "https://acme.com:22/", "https://acme.com:3306/", "ftp://acme.com/",
    ],
)
async def test_validate_destination_blocks_private_and_prohibited(url):
    with pytest.raises((UnsafeURLError, InvalidURLError)):
        await validate_destination(url, public_resolver)


async def test_public_host_is_allowed():
    assert await validate_destination("https://acme.com/", public_resolver) == [PUBLIC_IP]


async def test_dns_rebinding_hostname_resolving_to_private_ip_is_blocked():
    async def evil(host, port):
        return ["127.0.0.1"]

    with pytest.raises(UnsafeURLError):
        await validate_destination("https://totally-public.example-site.com/", evil)


async def test_mixed_public_and_private_records_are_blocked():
    async def mixed(host, port):
        return [PUBLIC_IP, "10.0.0.1"]

    with pytest.raises(UnsafeURLError):
        await validate_destination("https://acme.com/", mixed)


async def test_unresolvable_host_is_an_invalid_url_error():
    import socket

    async def nxdomain(host, port):
        raise socket.gaierror("nope")

    with pytest.raises(InvalidURLError):
        await validate_destination("https://does-not-exist.example-site.com/", nxdomain)


async def test_fixture_host_exception_is_exact_host_and_port_only():
    assert await validate_destination("http://127.0.0.1:8099/x", public_resolver) == ["127.0.0.1"]
    with pytest.raises(UnsafeURLError):
        await validate_destination("http://127.0.0.1:8100/x", public_resolver)  # other port: still blocked
    with pytest.raises(UnsafeURLError):
        await validate_destination("http://127.0.0.2:8099/x", public_resolver)  # other host: still blocked
