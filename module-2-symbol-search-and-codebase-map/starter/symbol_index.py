"""Index a Python package by symbol with tree-sitter."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Query

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
    """Every class, method and function in a package, with its file and line span."""
    index = []
    for path in sorted((root / package).rglob("*.py")):
        # TODO Step 1: parse the file with PARSER, to get its syntax tree.
        # Hint: https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Parser.html#tree_sitter.Parser.parse
        tree = ...
        # TODO Step 2: run the DEFINITIONS query over the tree, from its root node. Each match
        # gives the index of the pattern it matched, 0 for a class and 1 for a function, and its
        # captures, by name.
        # Hint: https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.QueryCursor.html#tree_sitter.QueryCursor.matches
        matches = ...
        # TODO Step 3: for each match, add one entry to index, like this one:
        # {"name": "post", "kind": "method", "class": "Ledger",
        #  "path": "python_accounting/models/ledger.py", "start_line": 222, "end_line": 233}
        # - name: the text of the "name" capture.
        # - kind: "class" or "function", from the pattern index. A function defined inside a
        #   class is a "method".
        # - class: the name of the class it's defined in, from enclosing_class, or None.
        # - path: the file's path, relative to root.
        # - start_line and end_line: where the "class" or "function" capture starts and ends.
        #   Tree-sitter counts rows from 0, but line numbers start at 1.
        raise NotImplementedError
    return sorted(index, key=lambda s: (s["path"], s["start_line"]))
