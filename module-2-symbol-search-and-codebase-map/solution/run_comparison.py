"""Run the code questions through the grep baseline and the symbol tools, then
compare tokens, latency and correctness per question."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

# The functions every module shares live in shared/, at the top of the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.agent_runs import (
    find_trace_id,
    langfuse_client,
    run_agent,
    summarize,
    trace_url,
)

HERE = Path(__file__).resolve().parent
CODEBASE = HERE / "python-accounting"
QUESTIONS_FILE = HERE / "code_questions.yaml"
AGENTS = ("symbol-agent", "baseline-agent")


def is_correct(question: dict[str, Any], answer: str) -> bool:
    """The answer contains every expected fact."""
    return all(re.search(p, answer, re.IGNORECASE) for p in question["correct_if"])


def print_results(rows: list[dict[str, Any]]) -> None:
    """Print one line per question and agent, then the totals per agent."""
    print(
        f"\n{'question':<22} {'agent':<14} {'ok':<3} {'tokens':>8} {'calls':>6} {'latency':>8} {'cost':>8}"
    )
    for r in rows:
        ok = "yes" if r["correct"] else "no"
        print(
            f"{r['question']:<22} {r['agent']:<14} {ok:<3} {r['tokens']:>8} {len(r['tools']):>6} {r['latency_s']:>7.1f}s ${r['cost_usd']:>7.4f}"
        )

    print("\nTotals")
    for agent in AGENTS:
        mine = [r for r in rows if r["agent"] == agent]
        correct = sum(r["correct"] for r in mine)
        tokens = sum(r["tokens"] for r in mine)
        latency = sum(r["latency_s"] for r in mine)
        cost = sum(r["cost_usd"] for r in mine)
        print(
            f"  {agent:<14} correct {correct}/{len(mine)}  tokens {tokens}  latency {latency:.1f}s  cost ${cost:.4f}"
        )

    print("\nTraces")
    for r in rows:
        print(f"  {r['question']:<22} {r['agent']:<14} {r['trace_url']}")


def main() -> None:
    questions = yaml.safe_load(QUESTIONS_FILE.read_text())["questions"]
    rows = []
    with langfuse_client() as client:
        for question in questions:
            for agent in AGENTS:
                print(f"Running {question['id']} with {agent}...")
                run = summarize(run_agent(agent, question["question"], CODEBASE))
                trace_id = find_trace_id(client, run["session_id"])
                rows.append(
                    {
                        "question": question["id"],
                        "agent": agent,
                        "correct": is_correct(question, run["answer"]),
                        "tools": [call["tool"] for call in run["tool_calls"]],
                        "tokens": run["tokens"],
                        "cost_usd": run["cost_usd"],
                        "latency_s": run["latency_s"],
                        "trace_url": trace_url(client, trace_id)
                        if trace_id
                        else "not found",
                    }
                )
    print_results(rows)


if __name__ == "__main__":
    main()
