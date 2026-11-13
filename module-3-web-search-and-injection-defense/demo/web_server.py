"""MCP server that gives an agent web search and web fetch."""

from __future__ import annotations

import os
from html.parser import HTMLParser

import httpx
from fastmcp import FastMCP

EXA_SEARCH_URL = "https://api.exa.ai/search"
MAX_RESULTS = 5
MAX_PAGE_CHARS = 12_000

mcp = FastMCP("web")


class PageText(HTMLParser):
    """Collect a page's text, skipping only scripts and styles."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self.skipping += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.skipping:
            self.skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self.skipping and data.strip():
            self.parts.append(data.strip())


def read_page(url: str) -> str:
    """Download a page and return its text, cut to MAX_PAGE_CHARS."""
    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    parser = PageText()
    parser.feed(response.text)
    return "\n".join(parser.parts)[:MAX_PAGE_CHARS]


@mcp.tool
def search(query: str) -> list[dict]:
    """Search the web for current information. Returns the title, URL, date and
    a short snippet of each result, not the full pages. Use fetch to read the
    pages worth reading.

    Args:
        query: What to search for, e.g. "standard VAT rate in Spain".
    """
    response = httpx.post(
        EXA_SEARCH_URL,
        headers={"x-api-key": os.environ["EXA_API_KEY"]},
        json={
            "query": query,
            "type": "auto",
            "numResults": MAX_RESULTS,
            "contents": {"highlights": True},
        },
        timeout=30,
    )
    response.raise_for_status()
    return [
        {
            "title": result.get("title"),
            "url": result["url"],
            "published": result.get("publishedDate"),
            "snippet": " ".join(result.get("highlights", [])),
        }
        for result in response.json()["results"]
    ]


@mcp.tool
def fetch(url: str) -> str:
    """Read the text of one web page. Use it on the search results worth reading.

    Args:
        url: The full address of the page.
    """
    return read_page(url)


@mcp.tool
def safe_fetch(url: str) -> str:
    """Read the text of one web page, marked as untrusted content. Use it on the
    search results worth reading.

    Args:
        url: The full address of the page.
    """
    return f"<untrusted_content>\n{read_page(url)}\n</untrusted_content>"


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
