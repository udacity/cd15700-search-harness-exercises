"""The tool registry: the tools the model gets, and dispatch by name."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from harness.tools.base import Tool, ToolError


class ToolRegistry:
    """Name-to-tool lookup, plus the JSON schemas sent to the model."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    @classmethod
    def allowed(cls, tools: list[Tool], allow: list[str]) -> ToolRegistry:
        """The tools the config allows, in its order."""
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
        """Each tool's name, description and argument schema."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.Args.model_json_schema()}
            for t in self._tools.values()
        ]

    def call(self, name: str, args: dict[str, Any]) -> str:
        """Validate the arguments with the tool's Args, then run it."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(
                f"unknown tool {name!r}",
                hint=f"available tools are: {', '.join(sorted(self._tools))}",
            )
        try:
            validated = tool.Args.model_validate(args)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors())
            raise ToolError(f"invalid arguments for {name}: {problems}", hint="fix them and call the tool again")
        return tool.call(validated)
