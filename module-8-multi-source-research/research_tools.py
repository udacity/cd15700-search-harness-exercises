"""The research agent's three sources, as harness tools:

- sql_query: SQL over the arXiv metadata, for counts, filters and authors.
- semantic_search: search by meaning over the abstracts, in Chroma, for methods and ideas.
- web_search: the local web search server, for how methods are used in practice.

Build the Chroma index once, before the first run:

    python3 research_tools.py
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import chromadb
import httpx
from chromadb.utils.embedding_functions.openai_embedding_function import OpenAIEmbeddingFunction

from harness.tools.base import ToolError, capped, require, truncate

MODULE = Path(__file__).resolve().parent
DB = MODULE / "data" / "arxiv.db"
STORE = MODULE / "chroma_db"
EMBEDDING_MODEL = "text-embedding-3-small"
WEB_URL = os.environ.get("WEB_SEARCH_URL", "http://127.0.0.1:8765")
MAX_ROWS = 50
MAX_BYTES = 20_000


def with_rationale(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """A tool's parameters, plus two the model must fill on every call: the sub-question
    the call answers, and why this tool fits it. The tool doesn't use them: they make the
    routing decisions visible in the event log and the trace."""
    return {"type": "object", "properties": {
        "sub_question": {"type": "string", "description": "The sub-question this call answers."},
        "why": {"type": "string", "description": "Why this tool fits that sub-question."},
        **properties,
    }, "required": ["sub_question", "why", *required]}


# ---------------------------------------------------------------- SQL over the metadata

def schema() -> str:
    """The CREATE TABLE statements of the arXiv database."""
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as db:
        return "\n".join(sql for (sql,) in db.execute("SELECT sql FROM sqlite_master WHERE type = 'table'"))


class SqlQuery:
    name = "sql_query"

    def __init__(self) -> None:
        self.description = (
            "Run one read-only SQL query (SQLite) on the arXiv metadata of 5,732 papers about "
            "retrieval-augmented generation, dense retrieval and reranking, from 2020 to 2025. "
            "Use it for counts, filters, rankings, dates and authors. Returns at most "
            f"{MAX_ROWS} rows. The tables:\n{schema()}"
        )

    def parameters(self) -> dict[str, Any]:
        return with_rationale({"sql": {"type": "string", "description": "One SELECT statement."}}, ["sql"])

    def call(self, args: dict[str, Any]) -> str:
        sql = require(args, "sql")
        if not re.match(r"(?is)^\s*(select|with)\b", sql) or ";" in sql.strip().rstrip(";"):
            raise ToolError("only a single SELECT query is allowed", hint="write one SELECT statement")
        try:
            with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as db:
                cursor = db.execute(sql)
                rows = cursor.fetchmany(MAX_ROWS + 1)
                columns = [c[0] for c in cursor.description]
        except sqlite3.Error as error:
            raise ToolError(f"SQL error: {error}", hint="fix the query using the tables in the tool description")
        result: dict[str, Any] = {"columns": columns, "rows": [list(r) for r in rows[:MAX_ROWS]]}
        if len(rows) > MAX_ROWS:
            result["notice"] = f"Only the first {MAX_ROWS} rows are shown. Aggregate in SQL, or add a filter."
        return truncate(json.dumps(result, ensure_ascii=False), MAX_BYTES)


# ---------------------------------------------------------------- semantic search over the abstracts

def collection() -> chromadb.Collection:
    embed = OpenAIEmbeddingFunction(api_key=os.environ["OPENAI_API_KEY"], model_name=EMBEDDING_MODEL,
                                    api_base=os.environ.get("OPENAI_BASE_URL"))
    return chromadb.PersistentClient(path=str(STORE)).get_or_create_collection(
        name="abstracts", embedding_function=embed, configuration={"hnsw": {"space": "cosine"}})


def build_index(batch_size: int = 500) -> int:
    """Embed every paper's title and abstract from arxiv.db into Chroma, with its year and
    category as metadata. Starts from empty."""
    client = chromadb.PersistentClient(path=str(STORE))
    if "abstracts" in [c.name for c in client.list_collections()]:
        client.delete_collection("abstracts")
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as db:
        papers = db.execute("SELECT arxiv_id, title, abstract, year, primary_category FROM papers").fetchall()
    abstracts = collection()
    for start in range(0, len(papers), batch_size):
        batch = papers[start:start + batch_size]
        abstracts.add(
            ids=[p[0] for p in batch],
            documents=[f"{p[1]}\n{p[2]}" for p in batch],
            metadatas=[{"arxiv_id": p[0], "title": p[1], "year": p[3], "primary_category": p[4]} for p in batch],
        )
        print(f"  {start + len(batch)} of {len(papers)} embedded")
    return len(papers)


class SemanticSearch:
    name = "semantic_search"
    description = (
        "Search the abstracts of the same arXiv papers by meaning. Use it for methods, ideas and "
        "findings, e.g. 'distilling a cross-encoder reranker into a dense retriever'. Returns the "
        "closest papers with their arXiv ID, title, year and the start of the abstract. "
        "Distance is cosine: lower is closer. To search only some papers, e.g. the ones a SQL "
        "query found, pass their arXiv IDs."
    )

    def parameters(self) -> dict[str, Any]:
        return with_rationale({
            "query": {"type": "string", "description": "What to look for, in plain words."},
            "k": {"type": "integer", "description": "How many papers to return, at most 10. Default 5."},
            "year_from": {"type": "integer", "description": "Only papers from this year on."},
            "year_to": {"type": "integer", "description": "Only papers up to this year."},
            "arxiv_ids": {"type": "array", "items": {"type": "string"},
                          "description": "Only search these papers, e.g. the IDs a SQL query returned."},
        }, ["query"])

    def call(self, args: dict[str, Any]) -> str:
        query = require(args, "query")
        filters = [{"year": {"$gte": args["year_from"]}}] if isinstance(args.get("year_from"), int) else []
        filters += [{"year": {"$lte": args["year_to"]}}] if isinstance(args.get("year_to"), int) else []
        if args.get("arxiv_ids"):
            filters.append({"arxiv_id": {"$in": [str(i) for i in args["arxiv_ids"]]}})
        where = filters[0] if len(filters) == 1 else {"$and": filters} if filters else None
        result = collection().query(query_texts=[query], n_results=capped(args.get("k"), 10) if args.get("k") else 5,
                                    where=where, include=["metadatas", "documents", "distances"])
        papers = [
            {"arxiv_id": arxiv_id, "title": meta["title"], "year": meta["year"], "distance": round(distance, 3),
             "abstract": doc.split("\n", 1)[1][:500]}
            for arxiv_id, meta, doc, distance in zip(result["ids"][0], result["metadatas"][0],
                                                     result["documents"][0], result["distances"][0])
        ]
        return truncate(json.dumps(papers, ensure_ascii=False), MAX_BYTES)


# ---------------------------------------------------------------- web search, on the local server

class WebSearch:
    name = "web_search"
    description = (
        "Search the web for how methods and tools are used in practice: libraries, frameworks, "
        "documentation and announcements. Returns pages with their URL, title and text."
    )

    def parameters(self) -> dict[str, Any]:
        return with_rationale({"query": {"type": "string", "description": "A web search query."}}, ["query"])

    def call(self, args: dict[str, Any]) -> str:
        query = require(args, "query")
        try:
            response = httpx.get(f"{WEB_URL}/search", params={"q": query, "k": 5}, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ToolError(f"web search is unavailable: {error}", hint="the web server may not be running")
        return truncate(json.dumps(response.json(), ensure_ascii=False), MAX_BYTES)


def all_tools() -> list:
    return [SqlQuery(), SemanticSearch(), WebSearch()]


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(MODULE / ".env")
    print(f"Building the Chroma index in {STORE} from {DB.name}")
    print(f"{build_index()} papers indexed")
