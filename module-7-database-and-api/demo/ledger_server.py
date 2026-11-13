"""MCP server that lets an agent query the company ledger, read-only.

The ledger is a SQLite database built with python-accounting. The agent gets two tools:
get_schema, to learn the tables and their columns, and run_query, to run the SQL it writes.
The connection is read-only, so even if the model writes a DELETE or an UPDATE,
SQLite refuses it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastmcp import FastMCP

DB = Path(__file__).resolve().parents[1] / "data" / "ledger.db"

mcp = FastMCP("ledger")


def connect() -> sqlite3.Connection:
    """Open the ledger read-only."""
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


@mcp.tool
def get_schema() -> str:
    """The ledger's tables, as the SQL that creates them: their columns, types and links
    to other tables. Read it before writing a query."""
    with connect() as db:
        return "\n\n".join(
            sql
            for (sql,) in db.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table'"
            )
        )


@mcp.tool
def run_query(sql: str) -> list[list]:
    """Run one SQL query on the ledger and return its rows, each as a list of values.
    The ledger is SQLite, and read-only.

    Args:
        sql: One SELECT statement, in SQLite syntax.
    """
    with connect() as db:
        return [list(row) for row in db.execute(sql).fetchall()]


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
