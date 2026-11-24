# Build and Evaluate an Agentic RAG on a Document Corpus

An AI inference company has an internal assistant that answers employees' questions from the company's documents: Slack threads, emails, tickets, wiki pages and more. Today it uses naive RAG: it searches once, then answers from whatever came back. When the first search misses, or when the answer isn't in the documents at all, nothing catches it.

The documents and questions are a subset of [EnterpriseRAG-Bench](https://huggingface.co/datasets/onyx-dot-app/EnterpriseRAG-Bench), a benchmark of realistic internal documents.

- **Documents:** 3,086, in [`documents.jsonl.gz`](../data/documents.jsonl.gz). They're the documents that answer the questions, mixed with 3,000 unrelated ones, so the search has to find the right ones among many.
- **Questions:** 50, in [`questions.jsonl`](../data/questions.jsonl), five from each of ten categories. They range from simple lookups (`basic`) to questions whose documents disagree (`conflicting_info`), or whose answer isn't in the documents at all (`info_not_found`). Each question comes with its gold documents, the ones that hold the answer, and its answer facts, which the evaluation checks answers against.

Your job is to build an agentic search tool that checks what it found, and rewrites the search when the results fall short. Then you'll measure where it beats naive RAG, and what it costs, across ten categories of questions.

## Exercise structure

- [`rag_server.py`](rag_server.py): the MCP server, with the `search_docs` tool and its two helpers: `critique`, which checks whether the chunks found answer the question, and `rewrite_query`, which writes a better search query.
- [`evaluate.py`](evaluate.py): answers each question with naive RAG and with the agent, scores retrieval and answers, and prints a table by mode and question category.
- [`opencode.jsonc`](opencode.jsonc): the agent configuration.
- [`.opencode/agents/agentic-rag-agent.md`](.opencode/agents/agentic-rag-agent.md): the agent's system prompt.
- [`rag_index.py`](../rag_index.py): chunks, embeds and searches the documents with Chroma. `retrieve(query)` returns the closest chunks, each with its `distance`, where lower is closer.
- [`build_index.py`](../build_index.py): builds the index.
- [`data/`](../data/): the questions and documents.
- [`shared/agent_runs.py`](../../shared/agent_runs.py): the functions that run the agent.

## Tasks

1. **Understand the questions.** Read one question from each category in [`questions.jsonl`](../data/questions.jsonl), like `conflicting_info`, `completeness` and `info_not_found`.
2. **Write the two checks.** In [`rag_server.py`](rag_server.py), complete:
   - `critique`, which asks the model whether the chunks answer the question: they're sufficient, something is missing, or the documents don't cover the question at all;
   - `rewrite_query`, which asks the model for a better search query, given what was wrong with the last one.
3. **Build the agentic search.** Complete `search_docs`. After each retrieval:
   - when the results are weak, none closer than `WEAK_DISTANCE`, rewrite the query without a critique. Two weak searches in a row mean the answer isn't in the documents;
   - otherwise, critique every chunk found so far. Stop when they're sufficient, or when the documents don't cover the question. When something is missing, rewrite the query.

   Stop after `MAX_RETRIEVALS` retrievals. When the answer isn't in the documents, tell the agent not to search again.
4. **Register the server.** Register it in [`opencode.jsonc`](opencode.jsonc) as a local MCP server named `rag`, and make sure the model sees your tool description directly. OpenCode starts the server from this folder. See OpenCode's [MCP servers](https://opencode.ai/v2/docs/mcp-servers) documentation.
5. **Implement the metrics.** In [`evaluate.py`](evaluate.py), complete:
   - `document_recall` and `precision_at_5`, which score retrieval against the gold documents;
   - `completeness` and `faithfulness`, which use the model as a judge to score the answer against the answer facts and the retrieved chunks.
6. **Compare the two modes.** Run `evaluate.py`, and compare naive and agentic RAG by category: retrieval, completeness, faithfulness, tokens, latency and retrievals. In which categories does the agentic search help, and where does it cost more without helping?

> **Important:** don't change `naive_rag` in `evaluate.py`, or the agent's prompt. The comparison should measure only the search.

## Set up and run

1. Set your keys for the model and for your Langfuse project.

   ```bash
   export OPENAI_API_KEY=<your key>
   export OPENAI_BASE_URL=<your base URL>
   export LANGFUSE_PUBLIC_KEY=<your project's public key>
   export LANGFUSE_SECRET_KEY=<your project's secret key>
   export LANGFUSE_BASE_URL=<your Langfuse address>
   ```

2. Build the index once, from the module folder. It embeds every document, and later runs reuse it.

   ```bash
   cd ..
   python3 build_index.py
   cd starter
   ```

3. Run the evaluation. The number is how many questions to run, from the top of `questions.jsonl`:

   ```bash
   python3 evaluate.py 10   # one question from each category, for a quick check
   python3 evaluate.py      # the first 20 questions, two from each category
   python3 evaluate.py 50   # all 50 questions
   ```

## Deliverables

- A completed [`rag_server.py`](rag_server.py), registered in [`opencode.jsonc`](opencode.jsonc) as `rag`.
- A completed [`evaluate.py`](evaluate.py).
- The table from `evaluate.py`, with both modes.
