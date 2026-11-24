"""MCP server that lets an agent navigate a codebase by pointer."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from fastmcp import FastMCP
from symbol_index import build_index

ROOT = Path(__file__).resolve().parent / "python-accounting"
MAX_RANGE_LINES = 200
MAX_SYMBOL_RESULTS = 30

mcp = FastMCP("symbols")


@cache
def get_index() -> list[dict]:
    """The symbol index, built the first time a tool needs it, then reused.

    Each entry looks like this:
    {"name": "post", "kind": "method", "class": "Ledger",
     "path": "python_accounting/models/ledger.py", "start_line": 222, "end_line": 233}
    """
    return build_index(ROOT, "python_accounting")


# TODO: write the description the model sees, as the docstring. It should make this tool the
# agent's first choice whenever it knows or can guess a name, and explain what it returns and
# how to use the results.
@mcp.tool
def search_symbol(name: str, kind: str | None = None) -> list[dict]:
    # TODO Step 1: find the symbols in the index, from get_index(), that match the given name and
    # kind. The name can be any part of a symbol's name, in any case, and the kind is optional.

    # TODO Step 2: return the matching entries from the index, as they are, in a list of at most
    # MAX_SYMBOL_RESULTS.
    raise NotImplementedError


# TODO: write the description the model sees, as the docstring. It should say that this tool
# reads a range of lines from a file, instead of the whole file, using the line spans from
# search_symbol, and explain what it returns: numbered lines, at most MAX_RANGE_LINES at a time,
# with a notice that says where to continue when the range was cut short.
@mcp.tool
def read_range(path: str, start_line: int, end_line: int) -> str:
    # TODO Step 1: check that the agent asked for a real file and a valid range. Raise a
    # ValueError that says what's wrong when:
    # - the path isn't a file inside ROOT
    # - start_line is below 1
    # - end_line comes before start_line
    # Hint: ROOT / "../.env" still starts with ROOT, but points outside it. Resolve the path, then
    # check that it's inside ROOT: see Path.resolve and Path.is_relative_to in
    # https://docs.python.org/3/library/pathlib.html

    # TODO Step 2: build the output as one string, with the lines from start_line to end_line,
    # one per row, each starting with its number, like
    # "222:     def post(session, transaction: Transaction) -> None:".
    # Stop reading at MAX_RANGE_LINES lines, or at the end of the file.

    # TODO Step 3: when the cap (MAX_RANGE_LINES) cut the range short, end the output with a
    # notice that says which line to continue from, like
    # "[Truncated at 200 lines. Continue from line 422.]".
    raise NotImplementedError


# TODO: write the description the model sees, as the docstring. It should say that this tool
# returns a map of the codebase: each module with the classes and functions it defines.
@mcp.tool
def codebase_map() -> str:
    # TODO Step 1: go through the index, from get_index(), and group the symbols' names by file
    # path, in the modules dict: each key is a file path, and its value is the list of class and
    # function names defined in that file. Leave out methods to keep the map small.
    modules: dict[str, list[str]] = {}

    # TODO Step 2: return the map as one string, one line per module, with its names separated
    # by commas, like "python_accounting/database/session.py: AccountingSession, get_session".
    raise NotImplementedError


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
