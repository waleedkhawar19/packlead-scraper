"""Local fixture website for testing without touching the internet.

    python -m tests.fixture_server            # serves http://127.0.0.1:8099 (and http://localhost:8099)

* Host 127.0.0.1:8099  -> "Northwind Box Co." (+ /directory/ pages)
* Host localhost:8099  -> "Greenleaf Organic Foods"
Everything here is fictional TEST DATA. Add ``TEST_FIXTURE_HOSTS=127.0.0.1:8099,localhost:8099`` to
backend/.env so the crawler is allowed to reach these private addresses (it is blocked otherwise)."""
from __future__ import annotations

import mimetypes
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE_ROOT = Path(__file__).parent / "fixtures" / "site"
HOST_DIRS = {"127.0.0.1": "northwind", "localhost": "greenleaf"}
PORT = 8099


class Handler(BaseHTTPRequestHandler):
    server_version = "FixtureServer/1.0"

    def log_message(self, fmt, *args):  # noqa: ANN001
        if "--quiet" not in sys.argv:
            sys.stderr.write("[fixture] " + fmt % args + "\n")

    def _site_dir(self) -> Path:
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return SITE_ROOT / HOST_DIRS.get(host, "northwind")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/old-contact":
            self.send_response(301)
            self.send_header("Location", "/contact.html")
            self.end_headers()
            return
        if path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
            return
        if path.startswith("/directory"):
            rel = path.lstrip("/")
            target = SITE_ROOT / (rel if rel.endswith(".html") else rel.rstrip("/") + "/index.html")
        else:
            rel = path.lstrip("/") or "index.html"
            if rel in ("contact-us", "contact", "about", "products"):
                rel += ".html"
            target = self._site_dir() / rel
        try:
            target = target.resolve()
            target.relative_to(SITE_ROOT.resolve())  # no path traversal out of the fixtures
        except (ValueError, OSError):
            return self._send(404, b"not found")
        if not target.is_file():
            return self._send(404, b"not found")
        ctype = mimetypes.guess_type(target.name)[0] or "text/plain"
        self._send(200, target.read_bytes(), ctype)

    def _send(self, code: int, body: bytes, ctype: str = "text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith("text/") else ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_in_thread(port: int = PORT) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Fixture site running on http://127.0.0.1:{PORT} and http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
