"""Run one question through the harness: build the loop from the config and the tools,
and log every event to its own session folder."""

from __future__ import annotations

from pathlib import Path

from langfuse import get_client

from harness.config import HarnessConfig
from harness.events import EventLog
from harness.loop import AgentLoop, RunResult
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


def run_question(question: str, config: HarnessConfig, tools: list[Tool], runs_dir: Path) -> RunResult:
    """Answer one question, or raise RunAborted when a limit is hit.
    The session's events go to runs_dir/<session>/events.jsonl."""
    registry = ToolRegistry.allowed(tools, config.tools)
    with EventLog.for_session(runs_dir) as events:
        loop = AgentLoop(
            client=config.model_client(),
            registry=registry,
            turn_cap=config.limits.turn_cap,
            system_prompt=config.system_prompt.render(),
            retry_cap=config.limits.retry_cap,
            token_budget=config.limits.token_budget,
            events=events,
        )
        try:
            return loop.run(question)
        finally:
            # Traces are sent in the background: send what's left before the program ends.
            get_client().flush()
