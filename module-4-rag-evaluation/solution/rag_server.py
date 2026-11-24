"""MCP server that searches the company's documents with agentic RAG: it rewrites
weak searches and checks what it found, up to three retrievals."""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

from fastmcp import FastMCP
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag_index import retrieve

MODEL = "gpt-5.2"
MAX_RETRIEVALS = 3
WEAK_DISTANCE = 0.6
MAX_CHUNKS = 10

mcp = FastMCP("rag")


@cache
def llm() -> OpenAI:
    return OpenAI()


def ask(prompt: str) -> tuple[str, int]:
    """Send one prompt to the model and return its reply and the tokens it used."""
    response = llm().responses.create(model=MODEL, input=prompt)
    return response.output_text.strip(), response.usage.total_tokens


def as_context(chunks: list[dict]) -> str:
    return "\n\n".join(f"[{chunk['doc_id']}] {chunk['text']}" for chunk in chunks)


def rewrite_query(question: str, problem: str) -> tuple[str, int]:
    """Ask the model for a better search query, given what was wrong with the last search.
    Returns the new query and the tokens used."""
    # TODO: write the prompt. Give the model the question and the problem with the last search,
    # and ask for one new search query that's more likely to find the answer, with nothing else
    # in its reply.
    prompt = (
        "You write queries for a search engine over a company's documents.\n"
        f"Question: {question}\n"
        f"The last search had this problem: {problem}\n"
        "Write one new search query that is more likely to find the answer. "
        "Reply with the query only."
    )
    return ask(prompt)


def critique(question: str, chunks: list[dict]) -> tuple[str, str, int]:
    """Ask the model whether the chunks answer the question.

    Returns the verdict, what's missing, and the tokens used. The verdict is "sufficient",
    "missing" when they answer it only in part, or "not_found" when the documents don't cover
    the question at all.
    """
    # TODO Step 1: write the prompt. Give the model the question and the chunks, with
    # as_context(), and ask it to reply SUFFICIENT, MISSING: followed by what's missing, or
    # NOT_FOUND.
    prompt = (
        f"Question: {question}\n\n"
        f"Retrieved documents:\n{as_context(chunks)}\n\n"
        "Do these documents contain everything needed to answer the question? "
        "Reply SUFFICIENT if they do. Reply MISSING: followed by what is missing, "
        "if they answer it only in part. Reply NOT_FOUND if they don't cover the "
        "question at all."
    )
    reply, tokens = ask(prompt)
    # TODO Step 2: turn the reply into the verdict and what's missing. For example, the reply
    # "MISSING: the launch date" gives ("missing", "the launch date", tokens).
    verdict = reply.strip().upper()
    if verdict.startswith("SUFFICIENT"):
        return "sufficient", "", tokens
    if verdict.startswith("NOT_FOUND"):
        return "not_found", "", tokens
    return "missing", reply.split(":", 1)[-1].strip(), tokens


@mcp.tool
def search_docs(query: str) -> dict:
    """Search the company's documents, such as Slack threads, emails, tickets and
    wiki pages. It rewrites the search and tries again when the results don't
    answer the question. Returns the best chunks, each with its document ID,
    title, source and text.

    Args:
        query: The question you want answered, in plain words.
    """
    chunks: dict[str, dict] = {}  # every chunk found so far, by chunk_id
    queries = [query]
    tokens = 0  # the tokens used by rewrite_query and critique
    current = query
    weak_in_a_row = 0
    not_found = False
    for retrievals in range(1, MAX_RETRIEVALS + 1):
        # TODO Step 1: retrieve chunks for the current query, with retrieve() from rag_index.py. Add
        # each one to chunks, under its chunk_id, unless it's already there: a rewritten query often
        # finds some of the same chunks again.
        results = retrieve(current)
        for chunk in results:
            chunks.setdefault(chunk["chunk_id"], chunk)
        # TODO Step 2: stop after the last retrieval allowed.
        if retrievals == MAX_RETRIEVALS:
            break
        # TODO Step 3: find what was wrong with this search.
        # - When the results are weak, none of them closer than WEAK_DISTANCE, the problem is that
        #   they were only weakly related to the question. After two weak searches in a row, stop,
        #   and set not_found.
        # - Otherwise, critique every chunk kept so far. Stop when they're sufficient, or when the
        #   documents don't cover the question, and set not_found. When something is missing,
        #   that's the problem.
        if not results or min(chunk["distance"] for chunk in results) > WEAK_DISTANCE:
            weak_in_a_row += 1
            if weak_in_a_row == 2:
                not_found = True
                break
            problem = "The results were only weakly related to the question."
        else:
            weak_in_a_row = 0
            verdict, problem, used = critique(query, list(chunks.values()))
            tokens += used
            if verdict == "sufficient":
                break
            if verdict == "not_found":
                not_found = True
                break
        # TODO Step 4: rewrite the query from the problem, and add it to queries.
        current, used = rewrite_query(query, problem)
        tokens += used
        queries.append(current)
    # TODO Step 5: keep the MAX_CHUNKS closest chunks found, the ones with the lowest distance.
    best = sorted(chunks.values(), key=lambda chunk: chunk["distance"])[:MAX_CHUNKS]
    result = {
        "chunks": best,
        "queries": queries,
        "retrievals": retrievals,
        "llm_tokens": tokens,
    }
    # TODO Step 6: when the answer isn't in the documents, add a "note" to the result that tells
    # the agent not to search again, and to tell the user.
    if not_found:
        result["note"] = "The documents don't seem to contain the answer. Don't search again: tell the user."
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
