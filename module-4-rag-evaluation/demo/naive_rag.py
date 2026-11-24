"""Naive RAG pipeline: retrieve -> answer

python3 naive_rag.py "your question"
"""

from __future__ import annotations

import sys
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag_index import load_questions, retrieve

MODEL = "gpt-5.2"
INSTRUCTIONS = (
    "Answer the question using only the documents below, and cite the document IDs "
    "you used. If the documents don't contain the answer, say so."
)


def answer(question: str) -> tuple[list[dict], str]:
    """Retrieve once, then ask the model to answer from what came back."""
    chunks = retrieve(question)
    context = "\n\n".join(f"[{chunk['doc_id']}]\n{chunk['text']}" for chunk in chunks)
    response = OpenAI().responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=f"Documents:\n{context}\n\nQuestion: {question}",
    )
    return chunks, response.output_text


if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else load_questions()[0]["question"]
    chunks, text = answer(question)
    print(f"Question: {question}\n\nRetrieved:")
    for chunk in chunks:
        print(
            f"  {chunk['distance']:.3f}  {chunk['doc_id']}  {chunk['source_type']:<12} {chunk['title'][:60]}"
        )
    print(f"\nAnswer:\n{text}")
