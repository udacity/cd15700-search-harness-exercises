"""Run one question through the harness."""

from __future__ import annotations

from harness.config import HarnessConfig
from harness.loop import AgentLoop, RunResult
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry
from langfuse import get_client


def run_question(question: str, config: HarnessConfig, tools: list[Tool]) -> RunResult:
    """Answer one question with the tools the config allows."""
    loop = AgentLoop.from_config(
        config, ToolRegistry.allowed(tools, config.tools.allow)
    )
    try:
        return loop.run(question)
    finally:
        get_client().flush()
