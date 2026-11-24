# Freshness Verification and Stale-Memory Rejection

A CI triage agent remembers what it learned in past sessions: for each failing build, the root cause and the workaround, saved as a memory with its provenance: the repo, the commit it was written at, the files involved and the session. But the code moves on. A memory that was true at its commit can describe code that has since changed, and an agent that trusts it chases a fix that no longer applies.

Your job is to check each memory just in time, right before it's returned, against the code at HEAD, with git and ripgrep: keep it, refresh it, or reject it. Memories that have gone unused for too long are dropped too.

The data is built for this exercise: `invoicekit`, a small fictional invoicing library with a real git history and two tags, `old` and `new`.

- **Memories:** 14, in [`memories.jsonl`](../data/memories.jsonl), from five triage sessions at the `old` tag. Each memory also records its evidence: the exact line of code its workaround depends on.
- **Questions:** 14 new failures at the `new` tag, each with the memory that should match it and its expected verdict: 4 valid, 4 refreshed, 4 stale and 2 expired.

## Exercise structure

- [`memory_server.py`](memory_server.py): the MCP server, with the `recall_memory` tool and the checks behind it: `changed_files`, `evidence_line`, `last_changed_by`, `removed_by`, `verify` and `expired`.
- [`evaluate.py`](evaluate.py): runs the 14 questions at the `new` tag, and scores retrieval accuracy, the verdicts, stale and expired rejection, and valid retention.
- [`memory_store.py`](../memory_store.py): the memory store, in Chroma. `search` finds the memories closest to a failure log, `update_memory` changes a memory's details, and `git` runs a git command in the repo.
- [`data/`](../data/): the memories, and [`build_data.py`](../data/build_data.py), which builds the repo, its CI failures, the triage sessions and the evaluation questions.

## Tasks

1. **Understand the memory records.** Read a few records in [`memories.jsonl`](../data/memories.jsonl): their repo, commit SHA, files, session and evidence. Once you've built the data, read the questions in `../data/eval/questions.json`.
2. **Find what changed.** Complete `changed_files` in [`memory_server.py`](memory_server.py): the memory's files that differ between its commit and HEAD.
3. **Find the evidence.** Complete `evidence_line`, which finds the memory's evidence in the code at HEAD, and `last_changed_by` and `removed_by`, which find the commit that last changed the evidence line, or the one that changed or removed it.
4. **Verify each memory.** Complete `verify`. A memory is valid when its files haven't changed, refreshed when they changed but its evidence is still there, and stale when its evidence was changed or removed.
5. **Expire unused memories.** Complete `expired`: a memory expires when more than `MAX_UNUSED_SESSIONS` sessions have passed since it was last used.
6. **Recall only what holds.** Complete `recall_memory`. It searches the memories, drops the expired ones, verifies the rest, and returns the usable ones with their root cause and workaround, and the rejected ones with why.
7. **Score it.** Complete the scoring in [`evaluate.py`](evaluate.py), then run it.

> **Important:** don't change [`memories.jsonl`](../data/memories.jsonl) or the repo in `../data/repo/`. The questions' expected verdicts depend on them.

## Set up and run

1. Build the data once: the repo, its CI failures, the triage sessions and the questions.

   ```bash
   python3 ../data/build_data.py
   ```

2. Set your keys for the model. The memory store uses them to embed the memories.

   ```bash
   export OPENAI_API_KEY=<your key>
   export OPENAI_BASE_URL=<your base URL>
   ```

3. Run the evaluation. It checks out the `new` tag, and goes back to `old` at the end.

   ```bash
   python3 evaluate.py
   ```

## Deliverables

- A completed [`memory_server.py`](memory_server.py).
- A completed [`evaluate.py`](evaluate.py).
- The output of `evaluate.py`.
