import pytest

from app.services.email_validator import (
    EmailValidator, check_syntax, is_placeholder, is_role_based,
    STATUS_INVALID, STATUS_MX, STATUS_NO_MX, STATUS_PLACEHOLDER, STATUS_SYNTAX_OK, STATUS_UNVERIFIED,
)


@pytest.mark.parametrize("email,ok", [
    ("info@acme.com", True), ("first.last+tag@sub.acme.co.uk", True), ("a@b.io", True),
    ("plain", False), ("a@@b.com", False), ("a@b", False), (".a@b.com", False), ("a..b@c.com", False), ("a@-b.com", False),
    ("a@b.c", False), ("a b@c.com", False), ("x" * 65 + "@acme.com", False), ("a@" + "b" * 64 + ".com", False), ("", False),
])
def test_syntax(email, ok):
    assert check_syntax(email)[0] is ok


@pytest.mark.parametrize("email", ["you@example.com", "name@domain.com", "test@test.com", "yourname@gmail.com", "john.doe@acme.com", "user@sentry.io", "a@b.invalid"])
def test_placeholders_detected(email):
    assert is_placeholder(email)


@pytest.mark.parametrize("email,role", [("info@acme.com", True), ("Sales@acme.com", True), ("orders@acme.com", True), ("contact@acme.com", True),
                                         ("support@acme.com", True), ("no-reply@acme.com", True), ("maria.lopez@acme.com", False)])
def test_role_based(email, role):
    assert is_role_based(email) is role


def lookup_returning(outcome, hosts=(), msg=""):
    async def lookup(domain):
        return outcome, list(hosts), msg

    return lookup


async def test_mx_found_is_not_described_as_deliverable():
    v = EmailValidator(lookup=lookup_returning("mx", ["mx1.acme.com"]))
    r = await v.validate("info@acme.com")
    assert r.status == STATUS_MX and r.is_role_based
    assert "does not confirm" in r.detail.lower() or "not confirm" in r.detail.lower()


@pytest.mark.parametrize("outcome,status", [("a", STATUS_MX), ("none", STATUS_NO_MX), ("error", STATUS_UNVERIFIED)])
async def test_dns_outcomes_map_to_statuses(outcome, status):
    r = await EmailValidator(lookup=lookup_returning(outcome, ["h"], "boom")).validate("x1@acme.com")
    assert r.status == status


async def test_lookup_exception_is_unverified_not_crash():
    async def boom(domain):
        raise RuntimeError("dns down")

    r = await EmailValidator(lookup=boom).validate("sales@acme.com")
    assert r.status == STATUS_UNVERIFIED


async def test_invalid_and_placeholder_skip_dns():
    calls = []

    async def lookup(domain):
        calls.append(domain)
        return "mx", ["h"], ""

    v = EmailValidator(lookup=lookup)
    assert (await v.validate("broken@@acme.com")).status == STATUS_INVALID
    assert (await v.validate("you@example.com")).status == STATUS_PLACEHOLDER
    assert calls == []


async def test_without_mx_check_status_is_syntax_valid_and_dns_is_cached_per_domain():
    calls = []

    async def lookup(domain):
        calls.append(domain)
        return "mx", ["h"], ""

    v = EmailValidator(lookup=lookup)
    assert (await v.validate("a1@acme.com", check_mx=False)).status == STATUS_SYNTAX_OK
    out = await v.validate_many(["one1@acme.com", "two2@acme.com", "three@beta.org", "ONE1@acme.com"])
    assert len(out) == 3 and sorted(calls) == ["acme.com", "beta.org"]
