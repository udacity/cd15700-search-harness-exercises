"""Run an OpenCode agent and find its Langfuse trace. Every module's exercise uses these."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx


def run_agent(agent: str, question: str, codebase: Path) -> dict[str, Any]:
    """Run one agent on one question inside a codebase and return its exported session."""
    # OpenCode takes its working folder from PWD, so point PWD at the codebase too.
    # The environment label lets us filter each agent's traces in Langfuse.
    env = {**os.environ, "PWD": str(codebase), "LANGFUSE_ENVIRONMENT": agent}
    run = subprocess.run(
        ["opencode", "run", "--standalone", "--format", "json", "--agent", agent, question],
        cwd=codebase,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if not run.stdout:
        raise RuntimeError(f"opencode run printed nothing:\n{run.stderr}")
    session_id = json.loads(run.stdout.splitlines()[0])["sessionID"]
    # Write the export to a file, not a pipe: a large export read through a pipe
    # can come back cut off.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        subprocess.run(
            ["opencode", "session", "export", session_id],
            cwd=codebase,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=True,
        )
        output.seek(0)
        return json.loads(output.read())


def summarize(session: dict[str, Any]) -> dict[str, Any]:
    """Pull the answer, tool calls, tokens, cost and latency out of a session."""
    answer = ""
    tool_calls = []
    for message in session["messages"]:
        if message.get("type") != "assistant":
            continue
        for item in message.get("content", []):
            if item.get("type") == "text":
                answer = item.get("text", "")
            elif item.get("type") == "tool":
                state = item.get("state", {})
                output = "\n".join(c.get("text", "") for c in state.get("content", []))
                tool_calls.append({"tool": item["name"], "status": state.get("status"), "output": output})
    info = session["info"]
    tokens = info["tokens"]
    return {
        "session_id": info["id"],
        "answer": answer,
        "tool_calls": tool_calls,
        "tokens": tokens["input"] + tokens["output"] + tokens["cache"]["read"] + tokens["cache"]["write"],
        "cost_usd": info["cost"],
        "latency_s": (info["time"]["updated"] - info["time"]["created"]) / 1000,
    }


def langfuse_client() -> httpx.Client:
    """An HTTP client for the Langfuse API, authenticated with the project's keys."""
    return httpx.Client(
        base_url=os.environ["LANGFUSE_BASE_URL"],
        auth=(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]),
        timeout=30,
    )


def find_trace_id(client: httpx.Client, session_id: str) -> str | None:
    """Find the trace of a session. The plugin puts OpenCode's session ID on
    every observation, but they take a few seconds to arrive, so keep checking."""
    for _ in range(20):
        response = client.get(
            "/api/public/v2/observations",
            params={"sessionId": session_id, "fields": "core", "limit": 1},
        )
        response.raise_for_status()
        observations = response.json()["data"]
        if observations:
            return observations[0]["traceId"]
        time.sleep(3)
    return None


def trace_url(client: httpx.Client, trace_id: str) -> str:
    """The link to a trace in the Langfuse UI."""
    project_id = client.get("/api/public/projects").json()["data"][0]["id"]
    return f"{str(client.base_url).rstrip('/')}/project/{project_id}/traces/{trace_id}"
