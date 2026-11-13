"""MCP server that recalls past triage findings, but only the ones that still hold.

A memory was true at the commit it was written at, but the code moves on.
So before a memory is returned, it's checked just in time against the code at HEAD:
- valid: its files haven't changed since its commit.
- refreshed: its files changed, but its evidence, the line it depends on, is still there,
  so it's re-verified at HEAD.
- stale: its evidence was changed or removed, so it's rejected.
Memories that have gone unused for too long are also rejected, as expired.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fastmcp import FastMCP
from ripgrep_rs import search_structured

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory_store import REPO, git, search, update_memory

REPO_NAME = "invoicekit"  # we only recall this repo's memories
CURRENT_SESSION = (
    6  # the triage session we're in now; sessions 1 to 5 wrote the memories
)
MAX_UNUSED_SESSIONS = 4  # a memory unused for more sessions than this expires
CANDIDATES = 3  # how many of the closest memories we check

mcp = FastMCP("memory")


def changed_files(memory: dict) -> list[str]:
    """The memory's files that changed between its commit and HEAD."""
    # TODO: list the memory's files that differ between its commit SHA and HEAD.
    # We only want the name of the files that changed
    # Hint: see the --name-only option in https://git-scm.com/docs/git-diff
    output = git(
        "diff", "--name-only", memory["commit_sha"], "HEAD", "--", *memory["files"]
    )
    return output.splitlines()


def evidence_line(memory: dict) -> int | None:
    """The line number of the memory's evidence in the current code, or None if it's gone.

    The evidence is the exact line the finding depends on.
    When the memory's files changed, it tells us whether the finding
    survived the change: the exact line is still there, or it was changed or removed.
    """
    # TODO: search the memory's evidence file for the exact evidence text, with ripgrep.
    # Hint: remember that ripgrep searches for patterns, not plain text. Our evidence is code, so it
    # contains special characters, like ( ) { } $, that change how ripgrep reads the pattern.
    hits = search_structured(
        patterns=[re.escape(memory["evidence"])],
        paths=[str(REPO / memory["evidence_file"])],
    )
    return hits[0].line_number if hits else None


def last_changed_by(memory: dict, line: int) -> str:
    """The commit that last changed the evidence line, as its short SHA and subject.

    git blame gives, for each line of a file, the commit that last changed it.
    """
    # TODO: blame only that line at HEAD, then get the commit's short SHA and subject with git log.
    # Hint: see the -L and --porcelain options in https://git-scm.com/docs/git-blame
    blame = git(
        "blame",
        "-L",
        f"{line},{line}",
        "--porcelain",
        "HEAD",
        "--",
        memory["evidence_file"],
    )
    sha = blame.split()[0]
    return git("log", "-1", "--format=%h %s", sha)


def removed_by(memory: dict) -> str:
    """The commit that changed or removed the memory's evidence, with git log -S (the pickaxe).

    git log -S <text> lists the commits that added or removed <text>, newest first.
    We search only the commits made between the memory's commit and HEAD.
    Since the evidence no longer exists at HEAD, the most recent commit in that list
    is the one that changed or removed it. Even a small edit to the line counts,
    because its exact text disappears.
    """
    # TODO: run the pickaxe on the evidence file, from the memory's commit to HEAD, and keep the newest commit.
    # Hint: see the -S option in https://git-scm.com/docs/git-log.
    # If nothing is found, return "an unknown commit".
    output = git(
        "log",
        "-S",
        memory["evidence"],
        "--format=%h %s",
        f"{memory['commit_sha']}..HEAD",
        "--",
        memory["evidence_file"],
    )
    return output.splitlines()[0] if output else "an unknown commit"


def verify(memory: dict) -> tuple[str, str]:
    """Check one memory against the code at HEAD, just before it's used.

    Each memory gets one of three statuses:
    - valid: its files haven't changed, so nothing it says can have changed.
    - refreshed: its files changed, but its evidence is still there, word for word,
      so the finding still holds. Its text stays the same: we only move its commit
      SHA to HEAD, to record that it was re-verified at this commit. Next time, we
      only check the changes made after it.
    - stale: its evidence was changed or removed. Its fix depends on code that no
      longer exists as it was, so the agent must not use it.

    Returns the status, and the reason the agent will see.
    """
    head = git("rev-parse", "HEAD")
    # TODO Step 1: a memory from HEAD itself, or whose files haven't changed since its commit, is valid.
    if memory["commit_sha"] == head or not changed_files(memory):
        return "valid", "its files haven't changed since its commit"
    # TODO Step 2: if the evidence is still there, the memory is refreshed: move its commit SHA to HEAD,
    # to record that it was re-verified there, and give the evidence's line and the commit that last changed it.
    # Hint: update_memory from memory_store changes a memory's metadata in the store.
    line = evidence_line(memory)
    if line is not None:
        update_memory(memory["id"], commit_sha=head)
        return (
            "refreshed",
            f"its files changed, but the evidence is still on line {line}, last changed by {last_changed_by(memory, line)}",
        )
    # TODO Step 3: otherwise, the evidence was changed or removed, so the memory is stale: give the commit that did it.
    return "stale", f"its evidence was changed or removed by {removed_by(memory)}"


def expired(memory: dict) -> bool:
    """Whether a memory has gone unused for too long, and should be dropped."""
    # TODO: a memory expires when more than MAX_UNUSED_SESSIONS sessions have passed since its last use.
    return CURRENT_SESSION - memory["last_used_session"] > MAX_UNUSED_SESSIONS


@mcp.tool
def recall_memory(failure_log: str) -> dict:
    """Find past triage findings that match a failing CI log. Every finding is checked
    against the current code first: you only get the ones that still hold, and the
    ones that were rejected, with why.

    Args:
        failure_log: The error lines from the failing build.
    """
    # TODO Step 1: search for this repo's memories closest to the failure log, with search from memory_store.
    # Then go through them one at a time, sorting each into the usable or the rejected memories:
    # TODO Step 2: if the memory has expired, reject it, without checking it against the code.
    # TODO Step 3: otherwise, verify it, and save its status and reason in the store using update_memory
    # TODO Step 4: if it's stale, reject it. The agent sees why, but not its workaround.
    # TODO Step 5: otherwise, it's usable: mark it as used in this session, and keep its root cause and workaround.
    # TODO Step 6: return the usable and the rejected memories.
    usable, rejected = [], []
    for memory, distance in search(failure_log, repo=REPO_NAME, top_k=CANDIDATES):
        if expired(memory):
            rejected.append(
                {
                    "id": memory["id"],
                    "distance": distance,
                    "status": "expired",
                    "reason": f"unused since session {memory['last_used_session']}",
                }
            )
            continue
        status, reason = verify(memory)
        update_memory(memory["id"], status=status, status_reason=reason)
        entry = {
            "id": memory["id"],
            "distance": distance,
            "status": status,
            "reason": reason,
        }
        if status == "stale":
            rejected.append(entry)
            continue
        update_memory(memory["id"], last_used_session=CURRENT_SESSION)
        usable.append(
            {
                **entry,
                "session": memory["session"],
                "files": memory["files"],
                "root_cause": memory["root_cause"],
                "workaround": memory["workaround"],
            }
        )
    return {"memories": usable, "rejected": rejected}


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
