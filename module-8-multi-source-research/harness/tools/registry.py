"""The tool registry: which tools the model gets, their schemas, and dispatch by name."""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool, ToolError


class ToolRegistry:
    """Name-to-tool lookup, plus the JSON schemas sent to the model."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    @classmethod
    def allowed(cls, tools: list[Tool], allow: list[str]) -> ToolRegistry:
        """Only the tools the config allows, in the order it lists them. A tool that isn't
        listed is never offered to the model. An allowed name with no tool is an error."""
        available = {t.name: t for t in tools}
        missing = [name for name in allow if name not in available]
        if missing:
            raise ToolError(
                f"tools.allow names {', '.join(missing)}, which this build cannot provide",
                hint=f"available tools are: {', '.join(sorted(available))}",
            )
        return cls([available[name] for name in allow])

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters()}
            for t in self._tools.values()
        ]

    def call(self, name: str, args: dict[str, Any]) -> str:
        """Run the tool called ``name`` with ``args``. An unknown name raises ToolError."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(
                f"unknown tool {name!r}",
                hint=f"available tools are: {', '.join(sorted(self._tools))}",
            )
        return tool.call(args)
