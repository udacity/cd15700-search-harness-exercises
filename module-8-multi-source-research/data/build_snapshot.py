"""Build this module's arXiv snapshot: papers about retrieval-augmented generation,
dense retrieval and reranking, from 2020 to 2025.

The metadata comes from the arXiv API (https://info.arxiv.org/help/api/), and arXiv's
metadata is CC0. arxiv.db is already in this folder, so you don't need to run this.
Running it again may give a few more or fewer papers, as arXiv updates its records.

    python3 build_snapshot.py

It writes arxiv.db next to this file: the papers in SQLite, in three tables:
papers, authors and categories. The Chroma index is built from it.
"""

from __future__ import annotations

import sqlite3
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
DB = HERE / "arxiv.db"

API_URL = "https://export.arxiv.org/api/query"
TOPIC = (
    '(abs:"retrieval-augmented" OR abs:"retrieval augmented" OR abs:"dense retrieval" '
    'OR abs:"dense retriever" OR abs:reranker OR abs:reranking OR abs:"re-ranker" OR abs:"re-ranking")'
)
CATEGORIES = "(cat:cs.CL OR cat:cs.IR OR cat:cs.LG OR cat:cs.AI)"
DATES = "submittedDate:[202001010000 TO 202512312359]"
QUERY = f"{TOPIC} AND {CATEGORIES} AND {DATES}"
PAGE_SIZE = 1000
PAUSE_S = 3.5  # arXiv asks for no more than one request every 3 seconds
RETRIES = 5

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def fetch_page(client: httpx.Client, start: int) -> tuple[int, list[ET.Element]]:
    """One page of results, and the total number of matches.
    The API sometimes returns an empty page by mistake, so we retry."""
    params = {"search_query": QUERY, "start": start, "max_results": PAGE_SIZE,
              "sortBy": "submittedDate", "sortOrder": "ascending"}
    for attempt in range(1, RETRIES + 1):
        response = client.get(API_URL, params=params)
        response.raise_for_status()
        feed = ET.fromstring(response.text)
        total = int(feed.findtext("opensearch:totalResults", namespaces=NS))
        entries = feed.findall("atom:entry", NS)
        if entries or start >= total:
            return total, entries
        print(f"  empty page at {start}, retry {attempt} of {RETRIES}")
        time.sleep(PAUSE_S * attempt)
    raise RuntimeError(f"no results at {start} after {RETRIES} tries")


def one_line(text: str | None) -> str:
    return " ".join((text or "").split())


def as_paper(entry: ET.Element) -> dict:
    # The ID is a URL like http://arxiv.org/abs/2005.11401v4: keep 2005.11401.
    arxiv_id = entry.findtext("atom:id", namespaces=NS).rsplit("/abs/", 1)[1].rsplit("v", 1)[0]
    return {
        "arxiv_id": arxiv_id,
        "title": one_line(entry.findtext("atom:title", namespaces=NS)),
        "abstract": one_line(entry.findtext("atom:summary", namespaces=NS)),
        "authors": [one_line(a.findtext("atom:name", namespaces=NS)) for a in entry.findall("atom:author", NS)],
        "primary_category": entry.find("arxiv:primary_category", NS).get("term"),
        "categories": [c.get("term") for c in entry.findall("atom:category", NS)],
        "published": entry.findtext("atom:published", namespaces=NS)[:10],
        "updated": entry.findtext("atom:updated", namespaces=NS)[:10],
        "doi": entry.findtext("arxiv:doi", namespaces=NS),
        "journal_ref": one_line(entry.findtext("arxiv:journal_ref", namespaces=NS)) or None,
        "comment": one_line(entry.findtext("arxiv:comment", namespaces=NS)) or None,
    }


def harvest() -> list[dict]:
    papers: dict[str, dict] = {}
    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"User-Agent": "course-data-builder/1.0"}) as client:
        start, total = 0, None
        while total is None or start < total:
            total, entries = fetch_page(client, start)
            for entry in entries:
                paper = as_paper(entry)
                papers[paper["arxiv_id"]] = paper
            start += PAGE_SIZE
            print(f"  {min(start, total)} of {total} requested, {len(papers)} papers so far")
            time.sleep(PAUSE_S)
    return sorted(papers.values(), key=lambda p: (p["published"], p["arxiv_id"]))


def write_db(papers: list[dict]) -> None:
    DB.unlink(missing_ok=True)
    with sqlite3.connect(DB) as db:
        db.executescript("""
            CREATE TABLE papers (
                arxiv_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                abstract TEXT NOT NULL,
                published DATE NOT NULL,   -- the date of the first version, YYYY-MM-DD
                year INTEGER NOT NULL,
                updated DATE NOT NULL,     -- the date of the latest version
                primary_category TEXT NOT NULL,
                doi TEXT,
                journal_ref TEXT,          -- where it was published, if the authors said
                comment TEXT               -- the authors' comment, e.g. pages or venue
            );
            CREATE TABLE authors (
                arxiv_id TEXT NOT NULL REFERENCES papers (arxiv_id),
                position INTEGER NOT NULL, -- 1 for the first author
                name TEXT NOT NULL
            );
            CREATE TABLE categories (
                arxiv_id TEXT NOT NULL REFERENCES papers (arxiv_id),
                category TEXT NOT NULL     -- e.g. cs.CL; a paper can have several
            );
            CREATE INDEX authors_name ON authors (name);
            CREATE INDEX categories_category ON categories (category);
        """)
        for p in papers:
            db.execute("INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (p["arxiv_id"], p["title"], p["abstract"], p["published"], int(p["published"][:4]),
                        p["updated"], p["primary_category"], p["doi"], p["journal_ref"], p["comment"]))
            db.executemany("INSERT INTO authors VALUES (?, ?, ?)",
                           [(p["arxiv_id"], i, name) for i, name in enumerate(p["authors"], start=1)])
            db.executemany("INSERT INTO categories VALUES (?, ?)",
                           [(p["arxiv_id"], c) for c in p["categories"]])


def main() -> None:
    print(f"Harvesting: {QUERY}")
    papers = harvest()
    write_db(papers)
    print(f"{len(papers)} papers written to {DB.name}")


if __name__ == "__main__":
    main()
