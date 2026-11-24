"""MCP server that gives an agent access to semantic search"""

from __future__ import annotations

import sys
from pathlib import Path

from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag_index import retrieve

mcp = FastMCP("rag")


@mcp.tool
def search_docs(query: str) -> list[dict]:
    """Search the company's documents, such as Slack threads, emails, tickets and
    wiki pages. Returns the closest chunks, each with its document ID, title,
    source and text.

    Args:
        query: What to search for, in plain words.
    """
    return retrieve(query)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
