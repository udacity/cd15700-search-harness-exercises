"""A small local web search server, over a fixed set of pages in data/web_pages.jsonl.

Each page is a short summary of a public source, like a library's documentation or
README, under that source's URL. A fixed set of pages keeps results the same on
every run, so answers and their URL citations can be checked.

    python3 web_server.py          # serves http://127.0.0.1:8765
    GET /search?q=colbert+library&k=5
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGES = Path(__file__).resolve().parent / "data" / "web_pages.jsonl"
HOST, PORT = "127.0.0.1", 8765
K1, B = 1.5, 0.75


def tokens(text: str) -> list[str]:
    """The words BM25 compares, in lowercase. A CamelCase name like GraphRAG also gives its
    parts, graph and rag, so a search for "graph RAG" finds it too."""
    words = []
    for word in re.findall(r"[A-Za-z0-9]+", text):
        words.append(word.lower())
        parts = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", word)
        if len(parts) > 1:
            words += [part.lower() for part in parts]
    return words


class Index:
    """BM25 over each page's title and text."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.docs = [
            Counter(tokens(f"{p['title']} {p['title']} {p['text']}")) for p in pages
        ]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.average = sum(self.lengths) / max(len(self.lengths), 1)
        frequency = Counter(term for d in self.docs for term in d)
        n = len(pages)
        self.idf = {
            t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()
        }

    def search(self, query: str, k: int = 5) -> list[dict]:
        terms = set(tokens(query))
        scores = []
        for i, doc in enumerate(self.docs):
            score = sum(
                self.idf[t]
                * doc[t]
                * (K1 + 1)
                / (doc[t] + K1 * (1 - B + B * self.lengths[i] / self.average))
                for t in terms
                if t in doc
            )
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return [
            {
                "url": self.pages[i]["url"],
                "title": self.pages[i]["title"],
                "text": self.pages[i]["text"],
            }
            for _, i in scores[:k]
        ]


def load_index() -> Index:
    with open(PAGES, encoding="utf-8") as f:
        return Index([json.loads(line) for line in f if line.strip()])


class Handler(BaseHTTPRequestHandler):
    index: Index

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path != "/search":
            self.send_error(404, "Only /search exists")
            return
        params = parse_qs(url.query)
        query = params.get("q", [""])[0]
        k = min(int(params.get("k", ["5"])[0]), 10)
        body = json.dumps(
            {"query": query, "results": self.index.search(query, k)}, ensure_ascii=False
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        print(f"web_server: {self.path}")


def main() -> None:
    Handler.index = load_index()
    print(
        f"Serving {len(Handler.index.pages)} pages on http://{HOST}:{PORT}/search?q=..."
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
