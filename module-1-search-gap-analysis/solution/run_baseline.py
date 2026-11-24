"""Run the baseline tasks through the OpenCode agent, grade each run, and link
it to its Langfuse trace."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

# The functions every module shares live in shared/, at the top of the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.agent_runs import find_trace_id, langfuse_client, run_agent, summarize, trace_url

HERE = Path(__file__).resolve().parent
CODEBASE = HERE / "python-accounting"
TASKS_FILE = HERE / "baseline_tasks.yaml"


def grade(task: dict[str, Any], run: dict[str, Any]) -> dict[str, bool]:
    """A pass must be correct and grounded in a source the agent read."""
    # TODO: correct = the answer matches every pattern in task["correct_if"]
    correct = all(re.search(p, run["answer"], re.IGNORECASE) for p in task["correct_if"])
    # TODO: grounded = every pattern matches the output of a completed tool call
    outputs = [c["output"] for c in run["tool_calls"] if c["status"] == "completed"]
    grounded = all(
        any(re.search(p, output, re.IGNORECASE) for output in outputs)
        for p in task["correct_if"]
    )
    # TODO: return a dict with "correct", "grounded" and "passed"
    return {"correct": correct, "grounded": grounded, "passed": correct and grounded}



def main() -> None:
    tasks = yaml.safe_load(TASKS_FILE.read_text())["tasks"]
    rows = []
    with langfuse_client() as client:
        for task in tasks:
            print(f"Running {task['id']}...")
            run = summarize(run_agent("baseline-agent", task["question"], CODEBASE))
            grades = grade(task, run)

            trace_id = find_trace_id(client, run["session_id"])

            rows.append({
                "task": task["id"],
                "team": task["team"],
                **grades,
                "tool_calls": len(run["tool_calls"]),
                "tokens": run["tokens"],
                "cost_usd": run["cost_usd"],
                "latency_s": run["latency_s"],
                "trace_url": trace_url(client, trace_id) if trace_id else "not found",
            })

    for row in rows:
        verdict = "PASS" if row["passed"] else "FAIL"
        print(f"\n[{verdict}] {row['task']} ({row['team']})")
        print(f"  correct: {row['correct']}  grounded: {row['grounded']}")
        print(f"  tool calls: {row['tool_calls']}  tokens: {row['tokens']}  cost: ${row['cost_usd']:.4f}  latency: {row['latency_s']:.1f}s")
        print(f"  trace: {row['trace_url']}")


if __name__ == "__main__":
    main()
