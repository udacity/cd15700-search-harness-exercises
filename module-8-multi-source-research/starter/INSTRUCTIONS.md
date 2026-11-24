# Implement A Research Agent with a Search Budget

A research team uses an agent to review the literature on retrieval-augmented generation. Its questions have several parts: a count from the paper metadata, a method from the abstracts, and how a tool is used in practice, from the web.

Your job is to add the checks that keep the agent's research on track. The model plans, searches and writes the answer. Your code checks its progress after every round of searches, ends the search when every part of the question is answered, when two rounds in a row find nothing new, or when the budget runs out, and makes sure every citation points to a real search result. Then you'll compare this agent with one that only has semantic search.

The agent doesn't run in OpenCode. It runs in a small Python harness, in [`harness/`](../harness/), that makes the model calls and runs the tools. Because the loop is plain Python, you can change how it works: your research loop, in [`research_loop.py`](research_loop.py), builds on the harness's `AgentLoop`.

The agent searches three sources, each through its own tool:

- **Paper metadata:** [`arxiv.db`](../data/arxiv.db), a SQLite database of 5,732 arXiv papers on retrieval and RAG, from 2020 to 2025, with their titles, abstracts, dates, categories and authors.
- **Abstracts:** the same papers' titles and abstracts, indexed for semantic search.
- **The web:** [`web_pages.jsonl`](../data/web_pages.jsonl), 22 pages about RAG libraries and tools, served by a local web search server.

The six questions, in [`questions.json`](../data/questions.json), each need more than one source, and come with the facts a correct answer must contain.

## Exercise structure

- [`research_loop.py`](research_loop.py): the research loop, with the structured answers the model fills in, `Plan`, `Reflection` and `Answer`, and `Sources`, which numbers every search result so the model can cite it.
- [`agent.yaml`](agent.yaml): the full agent, with the three search tools, and its budget.
- [`baseline.yaml`](baseline.yaml): the same agent with semantic search only, and its budget.
- [`evaluate.py`](evaluate.py): runs the questions with both configurations, scores each answer, and prints the comparison.
- [`.env.example`](.env.example): the keys to set, in a `.env` file.
- [`research_tools.py`](../research_tools.py): the three search tools: `sql_query` over the paper metadata, `semantic_search` over the abstracts, and `web_search` over the local web server.
- [`harness/`](../harness/): the agent harness. `ResearchLoop` extends its `AgentLoop`, and reuses its steps: `_start`, `_ask`, `_execute` and `_finish`. `_ask(messages, [], Schema)` asks the model for a structured answer.
- [`web_server.py`](../web_server.py): the local web search server.

## Tasks

1. **Understand the questions.** Read the six questions in [`questions.json`](../data/questions.json).
2. **Run the plan and the rounds.** In [`research_loop.py`](research_loop.py), write the `PLAN` and `REFLECT` instructions, and complete `_run`, `_plan`, `_search_round` and `_reflect`: ask for a plan first, then search in rounds, with a reflection after each one that records which sub-questions the sources answer, and whether the round answered a new one.
3. **Stop by rule.** Complete `_stop_reason`, which stops the search when the reflection says every sub-question is answered, or when two rounds in a row made no progress: no new sub-question answered.
4. **Enforce the budget.** Complete `_budget_used_up` and `_execute_within_budget`, which limit the searches and the tokens per question, and refuse any search beyond the budget. Stop searching early enough to leave `TOKEN_RESERVE` tokens for the last round and the answer, so the whole run is meant to stay within `token_budget`.
5. **Set the budget.** In [`agent.yaml`](agent.yaml), set `max_tool_calls` and `token_budget`: how many searches and how many tokens one question may use. Give [`baseline.yaml`](baseline.yaml) the same budget.
6. **Answer with checked citations.** Write the `ANSWER` instruction, and complete `_final_answer`, which asks for the answer, with the open sub-questions listed as gaps when the search stopped early. Every cited number must be a real source: drop the others, and record how many there were.
7. **Evaluate and compare.** Run [`evaluate.py`](evaluate.py) for both configurations, and compare their correctness, plan coverage, citation validity, cost, budget use, and calls per search type.

> **Important:** don't change [`harness/`](../harness/), [`research_tools.py`](../research_tools.py) or [`evaluate.py`](evaluate.py). Both configurations run on the same harness and tools, so the comparison measures only the search tools each one has.

## Set up and run

1. Copy `.env.example` to `.env`, and fill in your keys for the model and for your Langfuse project:

   ```bash
   cp .env.example .env
   ```

2. Build the semantic search index once, from the module folder:

   ```bash
   cd ..
   python3 research_tools.py
   cd starter
   ```

4. Run one question first, then all six. `evaluate.py` starts the local web server itself, and saves every answer in `runs/`.

   ```bash
   python3 evaluate.py q3
   python3 evaluate.py
   ```

## Deliverables

- A completed [`research_loop.py`](research_loop.py), and the budget in [`agent.yaml`](agent.yaml) and [`baseline.yaml`](baseline.yaml).
- The comparison from `evaluate.py` for both configurations, with the searches and tokens each question used against its budget, and the reason its search stopped: `sufficient`, `stalled` or `budget`.
