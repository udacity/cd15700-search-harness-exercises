"""Local stand-ins for the web: a public site with the fixture pages, and an
internal admin service that an SSRF attack would try to reach.

    http://127.0.0.1:8766/<page>.html      the fixture pages
    http://127.0.0.1:8766/search?q=...     a keyword search over them
    http://127.0.0.1:8766/redirect?to=...  an open redirect, as some real sites have
    http://127.0.0.1:8767/admin            the internal service, never meant to be fetched

Run it on its own with `python3 fixture_server.py`, or let run_defenses.py start it.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "web_fixtures"
HOST = "127.0.0.1"
PUBLIC_PORT = 8766
INTERNAL_PORT = 8767
SECRET = json.loads((FIXTURES / "fixtures.json").read_text())["internal_secret"]


def page_text(html: str) -> str:
    """Rough visible text of a page, for the search snippets."""
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>|<!--.*?-->", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class PublicSite(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def send(self, status: int, body: str, content_type: str = "text/html", headers: dict | None = None) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("content-type", f"{content_type}; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        if url.path == "/search":
            words = set(params.get("q", [""])[0].lower().split())
            results = []
            for page in sorted(FIXTURES.glob("*.html")):
                html = page.read_text(encoding="utf-8")
                title = re.search(r"(?is)<title>(.*?)</title>", html).group(1).strip()
                text = page_text(html)
                score = sum((title + " " + text).lower().count(word) for word in words)
                if score:
                    results.append({"title": title, "url": f"http://{HOST}:{PUBLIC_PORT}/{page.name}", "snippet": text[:200], "score": score})
            results.sort(key=lambda result: -result["score"])
            self.send(200, json.dumps({"results": results[:5]}), "application/json")
        elif url.path == "/redirect":
            self.send(302, "", headers={"location": params.get("to", ["/"])[0]})
        elif (FIXTURES / url.path.lstrip("/")).is_file() and url.path.endswith(".html"):
            self.send(200, (FIXTURES / url.path.lstrip("/")).read_text(encoding="utf-8"))
        else:
            self.send(404, "Not found")


class InternalService(PublicSite):
    def do_GET(self) -> None:
        self.send(200, f"Internal admin panel. Admin token: {SECRET}", "text/plain")


def start() -> None:
    """Start both servers in background threads."""
    for port, handler in ((PUBLIC_PORT, PublicSite), (INTERNAL_PORT, InternalService)):
        server = ThreadingHTTPServer((HOST, port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    start()
    print(f"Fixtures on http://{HOST}:{PUBLIC_PORT}, internal service on http://{HOST}:{INTERNAL_PORT}. Ctrl+C to stop.")
    threading.Event().wait()
