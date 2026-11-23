"""The tool definition, the error tools raise, and the output cap the loop applies."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel


class ToolError(Exception):
    """A tool failure the model should see. ``hint`` tells it what to do differently."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def as_payload(self) -> str:
        """The JSON the model receives: ``{"error": message, "hint": hint}``."""
        return json.dumps({"error": self.message, "hint": self.hint})


class Tool(Protocol):
    """A tool. Its arguments are a Pydantic model, ``Args``."""

    name: str
    description: str
    Args: type[BaseModel]

    def call(self, args: Any) -> str:
        """Run the tool and return its output as text."""
        ...


def truncate(text: str, max_bytes: int) -> str:
    """Cut ``text`` to ``max_bytes`` bytes, with a notice."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    kept = raw[:max_bytes].decode("utf-8", errors="ignore")
    return f"{kept}\n\n[output truncated: showing {len(kept.encode())} of {len(raw)} bytes]"
