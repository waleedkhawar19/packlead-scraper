"""Test configuration. Environment variables are set BEFORE the app is imported so every test runs
against a throw-away SQLite database and temp directories - your real data is never touched."""
import os
import tempfile
from pathlib import Path
from typing import Dict, Tuple

_TMP = Path(tempfile.mkdtemp(prefix="packlead-test-"))
os.environ.update(
    DATABASE_URL=f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    UPLOAD_DIR=str(_TMP / "uploads"),
    EXPORT_DIR=str(_TMP / "exports"),
    EMBEDDED_WORKER="false",
    TEST_FIXTURE_HOSTS="127.0.0.1:8099,localhost:8099",
    MIN_DOMAIN_DELAY="0",
    REQUEST_RETRIES="0",
    RETRY_BACKOFF_SECONDS="0",
    ENABLE_OCR="false",
    LOG_LEVEL="WARNING",
    ENVIRONMENT="development",
)

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from tests.fixture_server import start_in_thread  # noqa: E402

PUBLIC_IP = "93.184.216.34"


async def public_resolver(host: str, port: int):
    return [PUBLIC_IP]


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def fixture_site():
    server = start_in_thread(8099)
    yield "http://127.0.0.1:8099"
    server.shutdown()


Site = Dict[Tuple[str, str], Tuple[int, str, dict]]


def make_transport(site: Site, calls: list | None = None) -> httpx.MockTransport:
    """site maps (host, path) -> (status, body, headers). Unknown paths -> 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        path = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        if calls is not None:
            calls.append((host, path, request.url.host))
        entry = site.get((host, path))
        if entry is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        status, body, headers = entry
        headers = {"content-type": "text/html; charset=utf-8", **headers}
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, content=body.encode() if isinstance(body, str) else body, headers=headers)

    return httpx.MockTransport(handler)


def html(body: str, title: str = "Acme") -> str:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"
