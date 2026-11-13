"""MCP server that lets an agent query the company ledger, safely.

The model writes the SQL, so the server can't trust it. Three layers keep the ledger read-only:
1. check_statement refuses anything but a single SELECT, before it reaches the database.
2. authorize, SQLite's authorizer, lets a query read only the allow-listed tables.
3. The connection itself is read-only (mode=ro), so SQLite refuses any write.

Each query also has a time limit and a row cap, the schema is pruned to the tables a
question needs, and a failed query comes back to the model so it can correct it once.
"""

from __future__ import annotations

import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from fastmcp import FastMCP

DB = Path(__file__).resolve().parents[1] / "data" / "ledger.db"
# The tables the agent may read. The rest are python-accounting's internals.
ALLOWED_TABLES = {"account", "transaction", "line_item", "currency", "entity"}
# The tables almost every question needs.
CORE_TABLES = {"account", "transaction", "line_item"}
MAX_ROWS = 50
TIMEOUT_S = 2.0
MAX_RETRIES = 1  # corrected retries allowed after a failed query

mcp = FastMCP("ledger")


def connect() -> sqlite3.Connection:
    """Open the ledger read-only (mode=ro), with our authorizer watching every query."""
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db.set_authorizer(authorize)
    return db


def authorize(action, table, column, database, trigger) -> int:
    """SQLite's authorizer: SQLite calls it for every step of a query, like reading a
    column or calling a function, and the step only runs if it returns SQLITE_OK.

    We allow three kinds of steps:
    - the SELECT itself;
    - reading a table, only if it's in ALLOWED_TABLES;
    - calling a function, like SUM.
    """
    # TODO: allow the SELECT itself, reading from ALLOWED_TABLES, and calling functions.
    # Deny everything else.
    # Hint: see https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.set_authorizer
    # and the action codes in https://www.sqlite.org/c3ref/c_alter_table.html
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and table in ALLOWED_TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def check_statement(sql: str) -> None:
    """Refuse every query except read queries, before it reaches the database. A read
    query is a single statement that starts with SELECT, or with WITH, which names a
    sub-query before the SELECT. Anything else, like DELETE, DROP or PRAGMA, is refused.
    """
    # Comments are removed first, so a DELETE can't hide behind one.
    statement = (
        re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL)
        .strip()
        .rstrip(";")
        .strip()
    )
    # TODO Step 1: refuse more than one statement: a semicolon left in the middle means a second one.
    if ";" in statement:
        raise ValueError("Only one statement is allowed.")
    # TODO Step 2: refuse anything that doesn't start with SELECT or WITH.
    if not re.match(r"(?i)^(select|with)\b", statement):
        raise ValueError("Only SELECT queries are allowed. The ledger is read-only.")


def tables_for(question: str) -> list[str]:
    """The allowed tables a question needs: the core tables, plus any it names.

    This is schema pruning. The full schema is long, and most of it is noise for one
    question, so the model reads only the tables it's likely to need.
    """
    # TODO: start from CORE_TABLES, and add any allowed table the question names,
    # in the singular or the plural, like "currency" or "currencies".
    words = set(re.findall(r"[a-z_]+", question.lower()))
    return sorted(
        CORE_TABLES
        | {t for t in ALLOWED_TABLES if t in words or t.rstrip("y") + "ies" in words}
    )


@mcp.tool
def get_schema(question: str) -> str:
    """The ledger tables you need for a question, with the SQL that creates each one.
    Read it before writing a query.

    Args:
        question: The user's question, so only the relevant tables are returned.
    """
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as db:
        rows = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    # TODO Prune the database schema using tables_for and return only the tables
    # needed for the question
    wanted = set(tables_for(question))
    return "\n\n".join(sql for name, sql in rows if name in wanted) + (
        '\n\nNote: "transaction" is a reserved word in SQL, so write it in double quotes.'
    )


def limit_time(db: sqlite3.Connection) -> None:
    """Stop any query on this connection that runs longer than TIMEOUT_S."""
    # TODO Step 1: work out the deadline. Use time.monotonic(),
    # TODO Step 2: set a progress handler that returns 1 once the deadline has passed, and 0 before.
    # The handler should run every 1000 instructions.
    # Hint: see https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.set_progress_handler
    # Hint: see https://www.sqlite.org/c3ref/progress_handler.html
    deadline = time.monotonic() + TIMEOUT_S
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)


def fetch_capped(cursor: sqlite3.Cursor) -> dict:
    """Cap the query's output to MAX_ROWS rows, and return a message when the output is truncated.

    The cursor holds the result of the query execution. We return its column names
    and at most MAX_ROWS rows. If the query returned more, we add a notice, because without
    it the model would take the first rows for the whole result.

    Returns a dict like:
        {"columns": ["transaction_type", "count(*)"],
         "rows": [["CLIENT_INVOICE", 40], ["CLIENT_RECEIPT", 20]],
         "notice": "Only the first 50 rows are shown. ..."}   # only when rows were cut
    """
    # TODO Step 1: fetch one row more than MAX_ROWS, to know whether there were more.
    # Hint: a cursor hands out the query's rows on request, so you can fetch only the first few
    # instead of all of them. See fetchmany, and description for the column names, in
    # https://docs.python.org/3/library/sqlite3.html#sqlite3-cursor-objects
    rows = cursor.fetchmany(MAX_ROWS + 1)
    # TODO Step 2: build the result: the column names, and at most MAX_ROWS rows, each as a list.
    result = {
        "columns": [c[0] for c in cursor.description],
        "rows": [list(row) for row in rows[:MAX_ROWS]],
    }
    # TODO Step 3: if there were more rows, add a notice telling the model what to do instead.
    if len(rows) > MAX_ROWS:
        result["notice"] = (
            f"Only the first {MAX_ROWS} rows are shown. Aggregate in SQL, or add a filter."
        )
    return result


class RetryCounter:
    """Counts failed queries in a row, so the model gets max_retries chances to correct
    its query, and no more. A query that works resets the count."""

    def __init__(self, max_retries: int) -> None:
        self.max_retries = max_retries
        self.failures_in_a_row = 0

    def failed(self) -> bool:
        """Count one more failure. Returns whether the model may still retry."""
        # TODO: count the failure. The model may retry while there have been at most
        # max_retries failures in a row.
        self.failures_in_a_row += 1
        return self.failures_in_a_row <= self.max_retries

    def succeeded(self) -> None:
        """A query worked, so the next failure starts a new count."""
        self.failures_in_a_row = 0


# One counter for the whole server: it lasts as long as the server runs.
retries = RetryCounter(MAX_RETRIES)


def as_retry(error: Exception) -> dict:
    """A failed query, as an error the model can act on, with what to do next.

    The model gets MAX_RETRIES chances to correct its query. After that, it should
    stop and tell the user, rather than keep guessing.
    """
    # TODO Step 1: SQLite's errors for a refused table and a timeout don't say what to change,
    # so replace them with a message that does.
    message = str(error)
    if message == "not authorized" or message.startswith("access to"):
        message = f"Only these tables can be read: {', '.join(sorted(ALLOWED_TABLES))}."
    elif message == "interrupted":
        message = f"The query ran longer than {TIMEOUT_S:g} seconds and was stopped. Simplify it."
    # TODO Step 2: count the failure with retries. If the model may still retry, tell it to fix
    # the query and try once more. Otherwise, tell it to stop and tell the user.
    if retries.failed():
        return {"error": message, "instruction": "Fix the query and try once more."}
    return {
        "error": message,
        "instruction": "Stop retrying, and tell the user the query failed.",
    }


@mcp.tool
def run_query(sql: str) -> dict:
    """Run one SELECT query on the ledger, which is SQLite. Returns at most 50 rows.
    If the query fails, you get the error back and can correct it once.

    Args:
        sql: One SELECT statement.
    """
    # TODO Step 1: check the statement, then open the connection, limit its time, run the query,
    # and fetch the capped rows.
    # TODO Step 2: if any of that fails, with a sqlite3.Error or a ValueError, return as_retry(error).
    # TODO Step 3: otherwise, tell retries the query succeeded, and return the rows.
    try:
        check_statement(sql)
        with closing(connect()) as db:
            limit_time(db)
            result = fetch_capped(db.execute(sql))
    except (sqlite3.Error, ValueError) as error:
        return as_retry(error)
    retries.succeeded()
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
