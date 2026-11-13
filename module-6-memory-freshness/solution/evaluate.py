"""Run the 14 evaluation questions at the new tag, then score retrieval accuracy,
stale rejection, expiry and valid retention.

    python3 evaluate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import memory_server
from memory_store import DATA, build_store, git, load_memories


def main() -> None:
    questions = json.loads((DATA / "eval" / "questions.json").read_text())["questions"]
    git("checkout", "-q", "new")
    print(f"Checked out the new tag: {git('rev-parse', '--short', 'HEAD')}\n")

    retrieved = verdicts = 0
    stale_rejected = stale_total = expired_rejected = expired_total = kept = valid_total = 0
    print(
        f"{'question':<9} {'expected':<9} {'top match':<10} {'verdict':<10} {'expected':<10} reason"
    )
    for question in questions:
        # Start each question from the original memories: verifying one can refresh it.
        build_store(load_memories())
        result = memory_server.recall_memory(question["failure"])
        found = {
            entry["id"]: entry for entry in result["memories"] + result["rejected"]
        }
        ranked = sorted(found.values(), key=lambda entry: entry.get("distance", 9))
        top = ranked[0]["id"] if ranked else "-"
        expected_entry = found.get(
            question["expected_memory"], {"status": "not found", "reason": ""}
        )

        # TODO: retrieval is right when the closest memory is the expected one
        retrieved += top == question["expected_memory"]
        # TODO: the verdict is right when the expected memory got the expected status
        verdicts += expected_entry["status"] == question["expected_verdict"]
        # TODO: count stale and expired memories that were rejected, and valid ones that were kept
        if question["expected_verdict"] == "stale":
            stale_total += 1
            stale_rejected += expected_entry["status"] == "stale"
        elif question["expected_verdict"] == "expired":
            expired_total += 1
            expired_rejected += expected_entry["status"] == "expired"
        else:
            valid_total += 1
            kept += expected_entry["status"] in ("valid", "refreshed")
        print(
            f"{question['id']:<9} {question['expected_memory']:<9} {top:<10} {expected_entry['status']:<10} "
            f"{question['expected_verdict']:<10} {expected_entry['reason'][:70]}"
        )

    n = len(questions)
    print(f"\nRetrieval accuracy: {retrieved} of {n}")
    print(f"Verdicts right:     {verdicts} of {n}")
    print(f"Stale rejected:     {stale_rejected} of {stale_total}")
    print(f"Expired rejected:   {expired_rejected} of {expired_total}")
    print(f"Valid kept:         {kept} of {valid_total}")
    git("checkout", "-q", "old")


if __name__ == "__main__":
    main()
