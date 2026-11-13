"""Run the ten questions through the finance agent, then report accuracy, latency,
tool calls and cost per question, and check that the ledger wasn't changed.

    python3 evaluate.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from shared.agent_runs import run_agent, summarize

DATA = HERE.parent / "data"
AGENT = "finance-agent"
TOLERANCE = 0.005


def numbers_in(text: str) -> list[float]:
    """Every number written in a piece of text, e.g. "$29,750.00" -> 29750.0."""
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", text)]


def is_correct(question: dict, answer: str) -> bool:
    """A number is right within 0.5%. A name is right if the answer contains it."""
    if question["type"] == "text":
        return question["answer"].lower() in answer.lower()
    expected = float(question["answer"])
    return any(
        abs(n - expected) <= TOLERANCE * max(abs(expected), 1)
        for n in numbers_in(answer)
    )


def fingerprint() -> str:
    return hashlib.sha256((DATA / "ledger.db").read_bytes()).hexdigest()


def main() -> None:
    questions = json.loads((DATA / "questions.json").read_text())["questions"]
    before = fingerprint()
    rows = []
    for question in questions:
        print(f"Running {question['id']}: {question['question']}")
        run = summarize(run_agent(AGENT, question["question"], HERE))
        rows.append(
            {
                "id": question["id"],
                "correct": is_correct(question, run["answer"]),
                "calls": len(run["tool_calls"]),
                "errors": sum(
                    "error" in call["output"][:200] for call in run["tool_calls"]
                ),
                "latency_s": run["latency_s"],
                "tokens": run["tokens"],
                "cost_usd": run["cost_usd"],
            }
        )

    print(
        f"\n{'question':<9} {'ok':<4} {'calls':>5} {'errors':>6} {'latency':>8} {'tokens':>8} {'cost':>9}"
    )
    for r in rows:
        print(
            f"{r['id']:<9} {'yes' if r['correct'] else 'no':<4} {r['calls']:>5} {r['errors']:>6} "
            f"{r['latency_s']:>7.1f}s {r['tokens']:>8} ${r['cost_usd']:>8.4f}"
        )
    n = len(rows)
    print(f"\nCorrect: {sum(r['correct'] for r in rows)} of {n}")
    print(f"Average cost per question: ${sum(r['cost_usd'] for r in rows) / n:.4f}")
    print(
        f"Average latency: {sum(r['latency_s'] for r in rows) / n:.1f}s, average tool calls: {sum(r['calls'] for r in rows) / n:.1f}"
    )
    # TODO: show that no write reached the ledger: its contents must be unchanged
    print(f"Ledger unchanged: {fingerprint() == before}")


if __name__ == "__main__":
    main()
