"""Run the six research questions with the full agent and a semantic-only baseline,
score the answers, and compare the two.

    python3 evaluate.py                  # all six questions, both configurations
    python3 evaluate.py q1               # one question, both configurations
    python3 evaluate.py semantic-only    # all six questions, one configuration
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
load_dotenv(HERE / ".env")
import web_server
from harness.config import load_config
from harness.model import ModelError
from langfuse import get_client
from research_loop import build_loop
from research_tools import WEB_URL, all_tools

QUESTIONS = HERE.parent / "data" / "questions.json"
RUNS = HERE / "runs"
CONFIGS = {"full": HERE / "agent.yaml", "semantic-only": HERE / "baseline.yaml"}
SEARCH_TOOLS = ["sql_query", "semantic_search", "web_search"]
# gpt-5.2's price per token, in US dollars: https://openai.com/api/pricing
PRICE_INPUT = 1.75 / 1_000_000
PRICE_OUTPUT = 14.00 / 1_000_000


def has_fact(answer: str, fact: dict) -> bool:
    """Whether the answer contains any of the fact's strings, ignoring case.
    A number must appear as a whole number: 5 doesn't match 15, 2025 or 5.2."""
    for expected in fact["any_of"]:
        if expected.isdigit():
            if re.search(rf"(?<![\d.]){expected}(?!\.?\d)", answer):
                return True
        elif expected.lower() in answer.lower():
            return True
    return False


def correctness(question: dict, answer: str) -> float:
    """The share of the rubric's facts the answer contains."""
    return sum(has_fact(answer, fact) for fact in question["rubric"]) / len(question["rubric"])


def run_one(question: dict, config, search_tools: list) -> dict:
    """Run one question, and score its answer."""
    loop = build_loop(config, search_tools)
    started = time.monotonic()
    result = loop.run(question["question"])
    latency = time.monotonic() - started

    # Correctness: the share of the rubric's facts in the answer's claims. The gaps don't count.
    correct = correctness(question, " ".join(claim.text for claim in loop.answer.claims))
    # Coverage: the share of the plan's sub-questions the last reflection found answered.
    coverage = len(loop.answered) / len(loop.plan.sub_questions)
    # Citation validity: the share of the model's citations that pointed to a real source.
    citations, valid = loop.citation_check
    validity = valid / citations if citations else 0.0
    return {
        "id": question["id"],
        "correct": correct,
        "coverage": coverage,
        "validity": validity,
        "citations": citations,
        "calls": {tool: loop.searches.get(tool, 0) for tool in SEARCH_TOOLS},
        "rounds": loop.rounds,
        "stopped_by": loop.stopped_by,
        "searches": sum(loop.searches.values()),
        "max_searches": config.limits.max_tool_calls,
        "tokens": result.input_tokens + result.output_tokens,
        "token_budget": config.limits.token_budget,
        "cost": result.input_tokens * PRICE_INPUT + result.output_tokens * PRICE_OUTPUT,
        "latency": latency,
        "answer": result.final_text,
    }


def failed_run(question: dict, error: Exception) -> dict:
    """A question whose run failed. It scores 0."""
    return {"id": question["id"], "correct": 0.0, "coverage": 0.0, "validity": 0.0, "citations": 0,
            "calls": {tool: 0 for tool in SEARCH_TOOLS}, "rounds": 0, "stopped_by": f"error: {error}"[:60],
            "searches": 0, "max_searches": 0, "tokens": 0, "token_budget": 1, "cost": 0.0, "latency": 0.0,
            "answer": ""}


def print_table(name: str, rows: list[dict]) -> None:
    print(f"\n=== {name} ===")
    print(f"{'question':<9}{'correct':>8}{'coverage':>9}{'citations':>10}{'sql':>5}{'sem':>5}{'web':>5}"
          f"{'rounds':>7}{'searches':>9}{'tokens':>17}{'cost':>8}  stopped by")
    for r in rows:
        print(f"{r['id']:<9}{r['correct']:>8.2f}{r['coverage']:>9.2f}{r['validity']:>6.2f} ({r['citations']:>2})"
              f"{r['calls']['sql_query']:>5}{r['calls']['semantic_search']:>5}{r['calls']['web_search']:>5}"
              f"{r['rounds']:>7}{r['searches']:>6}/{r['max_searches']:<2}"
              f"{r['tokens']:>9,}/{r['token_budget']:<7,}  ${r['cost']:.3f}  {r['stopped_by']}")


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "correct": sum(r["correct"] for r in rows) / n,
        "coverage": sum(r["coverage"] for r in rows) / n,
        "validity": sum(r["validity"] for r in rows) / n,
        "calls": {tool: sum(r["calls"][tool] for r in rows) / n for tool in SEARCH_TOOLS},
        "cost": sum(r["cost"] for r in rows) / n,
        "latency": sum(r["latency"] for r in rows) / n,
        "searches": sum(r["searches"] for r in rows) / n,
        "tokens_share": sum(r["tokens"] / r["token_budget"] for r in rows) / n,
        "within_budget": sum(r["tokens"] <= r["token_budget"] for r in rows),
    }


def start_web_server() -> None:
    """Start the local web search server in the background, unless it's already running."""
    try:
        httpx.get(f"{WEB_URL}/search", params={"q": "test"}, timeout=2)
    except httpx.HTTPError:
        web_server.Handler.index = web_server.load_index()
        server = web_server.ThreadingHTTPServer((web_server.HOST, web_server.PORT), web_server.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()


def main() -> None:
    questions = json.loads(QUESTIONS.read_text())["questions"]
    picked = [arg for arg in sys.argv[1:] if arg not in CONFIGS]
    configs = [arg for arg in sys.argv[1:] if arg in CONFIGS] or list(CONFIGS)
    if picked:
        questions = [q for q in questions if q["id"] in picked]
    start_web_server()
    RUNS.mkdir(exist_ok=True)

    results = {}
    for name in configs:
        path = CONFIGS[name]
        config = load_config(path)
        search_tools = [tool for tool in all_tools() if tool.name in config.tools.allow]
        rows = []
        for question in questions:
            print(f"[{name}] {question['id']}: {question['question'][:80]}...")
            try:
                rows.append(run_one(question, config, search_tools))
            except ModelError as error:
                print(f"  failed: {error}")
                rows.append(failed_run(question, error))
            results[name] = rows
            # Save after every question.
            (RUNS / f"results-{name}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        print_table(name, rows)

    print("\n=== Comparison, averaged per question ===")
    print(f"{'':<15}{'correct':>8}{'coverage':>9}{'validity':>9}{'sql':>6}{'sem':>6}{'web':>6}"
          f"{'searches':>9}{'tokens':>8}{'cost':>8}{'latency':>9}  within token budget")
    for name, rows in results.items():
        s = summary(rows)
        print(f"{name:<15}{s['correct']:>8.2f}{s['coverage']:>9.2f}{s['validity']:>9.2f}"
              f"{s['calls']['sql_query']:>6.1f}{s['calls']['semantic_search']:>6.1f}{s['calls']['web_search']:>6.1f}"
              f"{s['searches']:>9.1f}{s['tokens_share']:>8.0%}  ${s['cost']:.3f}{s['latency']:>8.0f}s"
              f"  {s['within_budget']} of {len(rows)}")

    print(f"\nResults saved in {RUNS}")
    # Send the traces before the program ends.
    get_client().flush()


if __name__ == "__main__":
    main()
