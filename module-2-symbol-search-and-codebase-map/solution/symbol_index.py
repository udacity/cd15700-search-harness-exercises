"""Index a Python package by symbol with tree-sitter."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Query, QueryCursor

PY_LANGUAGE = Language(tspython.language())
PARSER = Parser(PY_LANGUAGE)
DEFINITIONS = Query(
    PY_LANGUAGE,
    """
    (class_definition name: (identifier) @name) @class
    (function_definition name: (identifier) @name) @function
    """,
)


def enclosing_class(node: Node) -> str | None:
    """The name of the class a definition sits inside, if any."""
    parent = node.parent
    while parent:
        if parent.type == "class_definition":
            return parent.child_by_field_name("name").text.decode()
        parent = parent.parent
    return None


def build_index(root: Path, package: str) -> list[dict]:
    """Every class, method and function in a package, with file and line span."""
    index = []
    for path in sorted((root / package).rglob("*.py")):
        tree = PARSER.parse(path.read_bytes())
        for pattern, captures in QueryCursor(DEFINITIONS).matches(tree.root_node):
            kind = "class" if pattern == 0 else "function"
            node = captures[kind][0]
            parent_class = enclosing_class(node)
            if parent_class and kind == "function":
                kind = "method"
            index.append(
                {
                    "name": captures["name"][0].text.decode(),
                    "kind": kind,
                    "class": parent_class,
                    "path": str(path.relative_to(root)),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                }
            )
    return sorted(index, key=lambda s: (s["path"], s["start_line"]))
