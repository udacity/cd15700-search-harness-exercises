"""MCP server that searches the company's documents with agentic RAG: it rewrites
weak searches and checks what it found, up to three retrievals."""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

from fastmcp import FastMCP
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    prompt = ...
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
    prompt = ...
    reply, tokens = ask(prompt)
    # TODO Step 2: turn the reply into the verdict and what's missing. For example, the reply
    # "MISSING: the launch date" gives ("missing", "the launch date", tokens).
    raise NotImplementedError


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
        results = ...
        # TODO Step 2: stop after the last retrieval allowed.
        # TODO Step 3: find what was wrong with this search.
        # - When the results are weak, none of them closer than WEAK_DISTANCE, the problem is that
        #   they were only weakly related to the question. After two weak searches in a row, stop,
        #   and set not_found.
        # - Otherwise, critique every chunk kept so far. Stop when they're sufficient, or when the
        #   documents don't cover the question, and set not_found. When something is missing,
        #   that's the problem.
        # TODO Step 4: rewrite the query from the problem, and add it to queries.
        raise NotImplementedError
    # TODO Step 5: keep the MAX_CHUNKS closest chunks found, the ones with the lowest distance.
    best = ...
    result = {
        "chunks": best,
        "queries": queries,
        "retrievals": retrievals,
        "llm_tokens": tokens,
    }
    # TODO Step 6: when the answer isn't in the documents, add a "note" to the result that tells
    # the agent not to search again, and to tell the user.
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
