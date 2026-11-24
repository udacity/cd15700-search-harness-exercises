"""The memory store the demo and the exercise share.

Each memory lives in Chroma: its text (failure, root cause, workaround) as an
embedding, so a new failure log can find it by meaning, and its details and
provenance (repo, commit SHA, files, session) as metadata.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions.openai_embedding_function import (
    OpenAIEmbeddingFunction,
)

MODULE = Path(__file__).resolve().parent
DATA = MODULE / "data"
REPO = DATA / "repo"
STORE = MODULE / "memory_store"
EMBEDDING_MODEL = "text-embedding-3-small"


def git(*args: str) -> str:
    """Run a git command in the project repo and return its output."""
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def load_memories() -> list[dict]:
    with open(DATA / "memories.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def memory_text(memory: dict) -> str:
    """The text we embed: what failed, why, and how to fix it."""
    return f"{memory['failure']}\nRoot cause: {memory['root_cause']}\nWorkaround: {memory['workaround']}"


@cache
def chroma() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=str(STORE))


def collection() -> chromadb.Collection:
    embed = OpenAIEmbeddingFunction(
        api_key=os.environ["OPENAI_API_KEY"],
        model_name=EMBEDDING_MODEL,
        api_base=os.environ.get("OPENAI_BASE_URL"),
    )
    return chroma().get_or_create_collection(
        name="memories", embedding_function=embed, configuration={"hnsw": {"space": "cosine"}}
    )


def build_store(memories: list[dict]) -> None:
    """Store every memory in Chroma: its text as an embedding, its details as metadata.
    Starts from empty."""
    if "memories" in [c.name for c in chroma().list_collections()]:
        chroma().delete_collection("memories")
    collection().add(
        ids=[m["id"] for m in memories],
        documents=[memory_text(m) for m in memories],
        metadatas=[
            {
                "repo": m["repo"],
                "commit_sha": m["commit"],
                "session": m["session"],
                # Metadata values can't be lists, so the files are stored as JSON.
                "files": json.dumps(m["files"]),
                "evidence_file": m["evidence_file"],
                "evidence": m["evidence"],
                "failure": m["failure"],
                "root_cause": m["root_cause"],
                "workaround": m["workaround"],
                "last_used_session": m["last_used_session"],
                "status": "unverified",
                "status_reason": "",
            }
            for m in memories
        ],
    )


def as_memory(memory_id: str, metadata: dict) -> dict:
    """A memory as a dict, from its Chroma metadata."""
    return {"id": memory_id, **metadata, "files": json.loads(metadata["files"])}


def get_memory(memory_id: str) -> dict:
    result = collection().get(ids=[memory_id], include=["metadatas"])
    return as_memory(memory_id, result["metadatas"][0])


def update_memory(memory_id: str, **fields) -> None:
    """Change some of a memory's details. Its text and embedding stay the same."""
    collection().update(ids=[memory_id], metadatas=[fields])


def search(failure_log: str, repo: str, top_k: int = 3) -> list[tuple[dict, float]]:
    """The memories closest to a failure log, only from the same repo, with their distance."""
    result = collection().query(
        query_texts=[failure_log], n_results=top_k, where={"repo": repo}, include=["metadatas", "distances"]
    )
    return [
        (as_memory(memory_id, metadata), round(distance, 3))
        for memory_id, metadata, distance in zip(result["ids"][0], result["metadatas"][0], result["distances"][0])
    ]
