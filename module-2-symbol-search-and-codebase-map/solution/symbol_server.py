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
    """Index the Python package the first time a tool needs it, then reuse it."""
    # Each entry looks like this:
    # {"name": "post", "kind": "method", "class": "Ledger",
    #  "path": "python_accounting/models/ledger.py",
    #  "start_line": 222, "end_line": 233}
    return build_index(ROOT, "python_accounting")


# TODO: write a description that makes this the agent's first choice
@mcp.tool
def search_symbol(name: str, kind: str | None = None) -> list[dict]:
    """Find where a class, method or function is defined. Use this first when
    you know or can guess a name. It returns pointers, not code: the file path
    and line span of each match. Pass them to read_range to see the code.

    Args:
        name: All or part of the symbol name, in any case, e.g. "post" or "ledger".
        kind: Optional filter: "class", "method" or "function".
    """
    # TODO: return the symbols in the index whose name contains `name`, ignoring case
    # TODO: apply the `kind` filter and cap the results at MAX_SYMBOL_RESULTS
    query = name.lower()
    matches = [
        symbol
        for symbol in get_index()
        if query in symbol["name"].lower() and (kind is None or symbol["kind"] == kind)
    ]
    return matches[:MAX_SYMBOL_RESULTS]


# TODO: write a description that steers the agent here instead of whole-file reads
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

    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT) or not target.is_file():
        raise ValueError(f"{path!r} is not a file in the codebase.")
    if start_line < 1 or end_line < start_line:
        raise ValueError("Use 1 <= start_line <= end_line.")

    # TODO: return the lines with line numbers, capped at MAX_RANGE_LINES
    # TODO: add a truncation notice when the cap cuts the range short
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    last_line = min(end_line, start_line + MAX_RANGE_LINES - 1, len(lines))
    numbered = [f"{n}: {lines[n - 1]}" for n in range(start_line, last_line + 1)]
    output = "\n".join(numbered)
    if last_line < min(end_line, len(lines)):
        output += f"\n[Truncated at {MAX_RANGE_LINES} lines. Continue from line {last_line + 1}.]"
    return output


# TODO: write a description that says when to use the map
@mcp.tool
def codebase_map() -> str:
    """Get a compact map of the package: each module with the classes and
    functions it defines. Use it to decide where to look when you don't know a
    symbol's name yet. It has no code and no method names.
    """
    # TODO: return one line per module, listing its classes and functions
    # TODO: leave out methods to keep the map small
    modules: dict[str, list[str]] = {}
    for symbol in get_index():
        if symbol["kind"] != "method":
            modules.setdefault(symbol["path"], []).append(symbol["name"])
    return "\n".join(f"{path}: {', '.join(names)}" for path, names in modules.items())


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
