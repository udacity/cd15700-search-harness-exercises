"""Chunk, embed and search this module's documents with Chroma and OpenAI embeddings.

The demo and the exercise share this index, so it's built (and paid for) once.
"""

from __future__ import annotations

import gzip
import json
import os
from functools import cache
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions.openai_embedding_function import (
    OpenAIEmbeddingFunction,
)

MODULE = Path(__file__).resolve().parent
DATA = MODULE / "data"
DB_PATH = MODULE / "chroma_db"
COLLECTION = "redwood_docs"
EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_CHARS = 1500
OVERLAP_CHARS = 200
TOP_K = 5
BATCH_SIZE = 100


def load_documents() -> list[dict]:
    with gzip.open(DATA / "documents.jsonl.gz", "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def load_questions() -> list[dict]:
    with open(DATA / "questions.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def chunk_document(document: dict, row: int) -> list[dict]:
    """Split a document into overlapping pieces. Each piece starts with the
    document's title, so it still makes sense on its own."""
    title = document["title"] or ""
    content = document["content"] or ""
    chunks = []
    for number, start in enumerate(range(0, max(len(content), 1), CHUNK_CHARS - OVERLAP_CHARS)):
        chunks.append(
            {
                "chunk_id": f"{row}-{number}",  # the dataset repeats a few document IDs
                "text": f"{title}\n\n{content[start:start + CHUNK_CHARS]}",
                "metadata": {
                    "doc_id": document["doc_id"],
                    "title": title,
                    "source_type": document["source_type"],
                },
            }
        )
    return chunks


@cache
def collection() -> chromadb.Collection:
    """The Chroma collection on disk, with OpenAI embeddings attached."""
    embed = OpenAIEmbeddingFunction(
        api_key=os.environ["OPENAI_API_KEY"],
        model_name=EMBEDDING_MODEL,
        api_base=os.environ.get("OPENAI_BASE_URL"),
    )
    client = chromadb.PersistentClient(path=str(DB_PATH))
    return client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=embed,
        configuration={"hnsw": {"space": "cosine"}},
    )


def build_index() -> None:
    """Chunk every document, embed the chunks and store them, unless that's done."""
    chunks = [chunk for row, document in enumerate(load_documents()) for chunk in chunk_document(document, row)]
    store = collection()
    if store.count() == len(chunks):
        print(f"The index already has all {len(chunks)} chunks.")
        return
    characters = sum(len(chunk["text"]) for chunk in chunks)
    print(f"Embedding {len(chunks)} chunks, about {characters // 4:,} tokens.")
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        store.upsert(
            ids=[chunk["chunk_id"] for chunk in batch],
            documents=[chunk["text"] for chunk in batch],
            metadatas=[chunk["metadata"] for chunk in batch],
        )
        print(f"  {min(start + BATCH_SIZE, len(chunks))} of {len(chunks)}")


def retrieve(query: str, top_k: int = TOP_K) -> list[dict]:
    """The top_k chunks closest to the query. A lower distance means closer."""
    result = collection().query(query_texts=[query], n_results=top_k)
    return [
        {
            "chunk_id": chunk_id,
            "doc_id": metadata["doc_id"],
            "title": metadata["title"],
            "source_type": metadata["source_type"],
            "distance": round(distance, 3),
            "text": text,
        }
        for chunk_id, text, metadata, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    ]
