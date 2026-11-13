"""Answer each question with naive RAG and with the agentic RAG agent, then score
retrieval and answers, and print a table by mode and question category.

    python3 evaluate.py        # the first 20 questions, two from each category
    python3 evaluate.py 50     # all 50 questions
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from functools import cache
from pathlib import Path
from statistics import mean

from openai import OpenAI

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parent))
from rag_index import load_questions, retrieve
from shared.agent_runs import run_agent, summarize

MODES = ("naive", "agentic")
AGENT = "agentic-rag-agent"
MODEL = "gpt-5.2"
JUDGE_MODEL = "gpt-5.2"
DEFAULT_QUESTIONS = 20
INSTRUCTIONS = (
    "You are an internal knowledge assistant. Answer the question "
    "using only the documents below. If they don't contain the answer, say so."
)


@cache
def llm() -> OpenAI:
    return OpenAI()


def judge(prompt: str) -> bool:
    """Ask the model a yes-or-no question."""
    reply = llm().responses.create(
        model=JUDGE_MODEL, input=prompt + "\n\nAnswer only yes or no."
    )
    return reply.output_text.strip().lower().startswith("yes")


def naive_rag(question: str) -> dict:
    """Naive RAG: retrieve once, then answer"""
    start = time.time()
    chunks = retrieve(question)
    context = "\n\n".join(f"[{chunk['doc_id']}] {chunk['text']}" for chunk in chunks)
    response = llm().responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=f"Documents:\n{context}\n\nQuestion: {question}",
    )
    return {
        "answer": response.output_text,
        "results": [{"chunks": chunks, "retrievals": 1, "llm_tokens": 0}],
        "tokens": response.usage.total_tokens,
        "latency_s": time.time() - start,
    }


def agentic_rag(question: str) -> dict:
    """Agentic RAG: the agent calls our search_docs tool, which rewrites and critiques."""
    run = summarize(run_agent(AGENT, question, HERE))
    return {
        "answer": run["answer"],
        "results": search_results(run),
        "tokens": run["tokens"],
        "latency_s": run["latency_s"],
    }


def search_results(run: dict) -> list[dict]:
    """The results of every completed call to our search tool, in order."""
    results = []
    for call in run["tool_calls"]:
        if call["tool"].startswith("rag_") and call["status"] == "completed":
            try:
                results.append(json.loads(call["output"]))
            except json.JSONDecodeError:
                pass
    return results


def retrieved_doc_ids(results: list[dict]) -> list[str]:
    """Every retrieved document ID, in order, without repeats."""
    ids = [chunk["doc_id"] for result in results for chunk in result["chunks"]]
    return list(dict.fromkeys(ids))


def document_recall(retrieved: list[str], gold: list[str]) -> float | None:
    """The share of gold documents that were retrieved. None if there are no gold documents."""
    # TODO: return None when there are no gold documents
    if not gold:
        return None
    # TODO: return the share of gold documents found in `retrieved`
    return len(set(gold) & set(retrieved)) / len(gold)


def precision_at_5(retrieved: list[str], gold: list[str]) -> float | None:
    """The share of the first five retrieved documents that are gold documents."""
    # TODO: return None when there are no gold documents
    if not gold:
        return None
    # TODO: count the gold documents among the first five retrieved, divided by five
    return len(set(retrieved[:5]) & set(gold)) / 5


def completeness(answer: str, facts: list[str]) -> float:
    """The share of the answer facts that the answer states, according to the judge."""
    # TODO: ask the judge, for each fact, whether the answer states it
    found = [
        judge(f"Answer:\n{answer}\n\nDoes this answer state this fact?\n{fact}")
        for fact in facts
    ]
    # TODO: return the share of facts found
    return sum(found) / len(facts) if facts else 0.0


def faithfulness(answer: str, chunks: list[dict], category: str) -> float | None:
    """1.0 if the judge finds every claim in the answer supported by the retrieved chunks.

    None for questions whose answer isn't in the documents"""
    # TODO: skip questions whose answer isn't in the documents
    # Hint: their question_type in data/questions.jsonl is "info_not_found".
    if category == "info_not_found":
        return None
    context = "\n\n".join(chunk["text"] for chunk in chunks)
    # TODO: ask the judge whether every claim in the answer is supported by the context
    supported = judge(
        f"Context:\n{context}\n\nAnswer:\n{answer}\n\n"
        "Is every claim in the answer supported by the context?"
    )
    return 1.0 if supported else 0.0


def evaluate(question: dict, mode: str) -> dict:
    run = (
        naive_rag(question["question"])
        if mode == "naive"
        else agentic_rag(question["question"])
    )
    results = run["results"]
    retrieved = retrieved_doc_ids(results)
    chunks = [chunk for result in results for chunk in result["chunks"]]
    gold = question["expected_doc_ids"]
    return {
        "mode": mode,
        "category": question["question_type"],
        "recall": document_recall(retrieved, gold),
        "precision_at_5": precision_at_5(retrieved, gold),
        "completeness": completeness(run["answer"], question["answer_facts"]),
        "faithfulness": faithfulness(run["answer"], chunks, question["question_type"]),
        "tokens": run["tokens"]
        + sum(result.get("llm_tokens", 0) for result in results),
        "latency_s": run["latency_s"],
        "retrievals": sum(result.get("retrievals", 0) for result in results),
    }


def average(rows: list[dict], key: str) -> str:
    values = [row[key] for row in rows if row[key] is not None]
    return f"{mean(values):.2f}" if values else "-"


def print_table(rows: list[dict]) -> None:
    columns = [
        "recall",
        "precision_at_5",
        "completeness",
        "faithfulness",
        "tokens",
        "latency_s",
        "retrievals",
    ]
    print(
        f"\n{'mode':<8} {'category':<26} {'n':>2} "
        + " ".join(f"{c[:11]:>11}" for c in columns)
    )
    groups = defaultdict(list)
    for row in rows:
        groups[(row["mode"], row["category"])].append(row)
        groups[(row["mode"], "ALL")].append(row)
    for (mode, category), group in sorted(
        groups.items(), key=lambda g: (g[0][0], g[0][1] == "ALL", g[0][1])
    ):
        print(
            f"{mode:<8} {category:<26} {len(group):>2} "
            + " ".join(f"{average(group, c):>11}" for c in columns)
        )


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_QUESTIONS
    rows = []
    for question in load_questions()[:limit]:
        for mode in MODES:
            print(
                f"Running {question['question_id']} ({question['question_type']}) in {mode} mode..."
            )
            rows.append(evaluate(question, mode))
    print_table(rows)


if __name__ == "__main__":
    main()
