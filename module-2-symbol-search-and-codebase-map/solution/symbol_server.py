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
    """Find where a class, method or function is defined. Use this first when
    you know or can guess a name. It returns pointers, not code: the file path
    and line span of each match. Pass them to read_range to see the code.

    Args:
        name: All or part of the symbol name, in any case, e.g. "post" or "ledger".
        kind: Optional filter: "class", "method" or "function".
    """
    # TODO Step 1: find the symbols in the index, from get_index(), that match the given name and
    # kind. The name can be any part of a symbol's name, in any case, and the kind is optional.
    query = name.lower()
    matches = [
        symbol
        for symbol in get_index()
        if query in symbol["name"].lower() and (kind is None or symbol["kind"] == kind)
    ]
    # TODO Step 2: return the matching entries from the index, as they are, in a list of at most
    # MAX_SYMBOL_RESULTS.
    return matches[:MAX_SYMBOL_RESULTS]


# TODO: write the description the model sees, as the docstring. It should say that this tool
# reads a range of lines from a file, instead of the whole file, using the line spans from
# search_symbol, and explain what it returns: numbered lines, at most MAX_RANGE_LINES at a time,
# with a notice that says where to continue when the range was cut short.
@mcp.tool
def read_range(path: str, start_line: int, end_line: int) -> str:
    """Read a span of lines from a file, up to 200 lines at a time. Use it with
    the line spans from search_symbol, instead of reading whole files. If the
    output says it was truncated, call it again from the next line.

    Args:
        path: File path relative to the codebase root, e.g. "python_accounting/models/ledger.py".
        start_line: First line to read, counting from 1.
        end_line: Last line to read.
    """
    # TODO Step 1: check that the agent asked for a real file and a valid range. Raise a
    # ValueError that says what's wrong when:
    # - the path isn't a file inside ROOT
    # - start_line is below 1
    # - end_line comes before start_line
    # Hint: ROOT / "../.env" still starts with ROOT, but points outside it. Resolve the path, then
    # check that it's inside ROOT: see Path.resolve and Path.is_relative_to in
    # https://docs.python.org/3/library/pathlib.html
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT) or not target.is_file():
        raise ValueError(f"{path!r} is not a file in the codebase.")
    if start_line < 1 or end_line < start_line:
        raise ValueError("Use 1 <= start_line <= end_line.")

    # TODO Step 2: build the output as one string, with the lines from start_line to end_line,
    # one per row, each starting with its number, like
    # "222:     def post(session, transaction: Transaction) -> None:".
    # Stop reading at MAX_RANGE_LINES lines, or at the end of the file.
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    last_line = min(end_line, start_line + MAX_RANGE_LINES - 1, len(lines))
    numbered = [f"{n}: {lines[n - 1]}" for n in range(start_line, last_line + 1)]
    output = "\n".join(numbered)
    # TODO Step 3: when the cap (MAX_RANGE_LINES) cut the range short, end the output with a
    # notice that says which line to continue from, like
    # "[Truncated at 200 lines. Continue from line 422.]".
    if last_line < min(end_line, len(lines)):
        output += f"\n[Truncated at {MAX_RANGE_LINES} lines. Continue from line {last_line + 1}.]"
    return output


# TODO: write the description the model sees, as the docstring. It should say that this tool
# returns a map of the codebase: each module with the classes and functions it defines.
@mcp.tool
def codebase_map() -> str:
    """Get a compact map of the package: each module with the classes and
    functions it defines. Use it to decide where to look when you don't know a
    symbol's name yet. It has no code and no method names.
    """
    # TODO Step 1: go through the index, from get_index(), and group the symbols' names by file
    # path, in the modules dict: each key is a file path, and its value is the list of class and
    # function names defined in that file. Leave out methods to keep the map small.
    modules: dict[str, list[str]] = {}
    for symbol in get_index():
        if symbol["kind"] != "method":
            modules.setdefault(symbol["path"], []).append(symbol["name"])
    # TODO Step 2: return the map as one string, one line per module, with its names separated
    # by commas, like "python_accounting/database/session.py: AccountingSession, get_session".
    return "\n".join(f"{path}: {', '.join(names)}" for path, names in modules.items())


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
