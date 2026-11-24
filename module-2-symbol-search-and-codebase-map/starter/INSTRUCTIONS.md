# Add Symbol Search and a Codebase Map to An Agent

An invoicing assistant answers questions by grepping and reading whole files of its bookkeeping software, [python-accounting](https://github.com/ekmungai/python-accounting). That works, but it spends tokens on code it doesn't need. Your job is to let it navigate by pointer instead, then measure what changes.

## Exercise structure

- [`symbol_server.py`](symbol_server.py): the MCP server, with three tools.
- [`symbol_index.py`](symbol_index.py): parses each file of the codebase into a syntax tree with tree-sitter, and indexes its classes, methods and functions.
- [`opencode.jsonc`](opencode.jsonc): the agent configuration.
- [`.opencode/agents/baseline-agent.md`](.opencode/agents/baseline-agent.md): the baseline agent, with `grep`, `glob` and `read`.
- [`.opencode/agents/symbol-agent.md`](.opencode/agents/symbol-agent.md): your agent, with the `symbols` server's tools and `grep` as a fallback.
- [`code_questions.yaml`](code_questions.yaml): eight questions with their expected answers.
- [`run_comparison.py`](run_comparison.py): runs every question with both agents and prints the comparison.
- [`shared/agent_runs.py`](../../shared/agent_runs.py): the functions that run the agent and find its trace.
- [`setup_codebase.sh`](setup_codebase.sh): clones the codebase at a pinned commit.

## Tasks

1. **Build the symbol index.** Complete `build_index` in [`symbol_index.py`](symbol_index.py). It parses every Python file in the package with tree-sitter, runs the given query, and records each class, method and function with its name, kind, class, path and line span. See the [py-tree-sitter](https://tree-sitter.github.io/py-tree-sitter/) documentation.
2. **Implement `search_symbol`** in [`symbol_server.py`](symbol_server.py). It returns file and line-span pointers. It matches any part of the name, ignores case, can filter by kind, and caps its results.
3. **Implement `read_range`.** It returns a span of lines with line numbers, capped at `MAX_RANGE_LINES`, with a notice when the cap cuts the range short.
4. **Implement `codebase_map`.** It returns one line per module, listing the module's classes and functions.
5. **Write the tool descriptions.** The model only sees each tool's docstring. Write them so the agent finds code with the map or symbol search, and reads only the range it needs, before falling back to `grep`.
6. **Register the server.** Register it in [`opencode.jsonc`](opencode.jsonc) as a local MCP server named `symbols`, and make sure the model sees your tool descriptions directly. OpenCode starts the server from inside `python-accounting/`. See OpenCode's [MCP servers](https://opencode.ai/v2/docs/mcp-servers) documentation.
7. **Compare the two agents.** Run [`run_comparison.py`](run_comparison.py), then open the traces in Langfuse. For each question, compare tokens, latency and correctness, and look at which tools each agent used.

> **Important:** don't change the agents' prompts. They're identical, so the comparison measures only the tools.

## Set up and run

1. Clone the codebase the agents search, into `python-accounting/`:

   ```bash
   bash setup_codebase.sh
   ```

2. Set your keys for the model and for your Langfuse project.

   ```bash
   export OPENAI_API_KEY=<your key>
   export OPENAI_BASE_URL=<your base URL>
   export LANGFUSE_PUBLIC_KEY=<your project's public key>
   export LANGFUSE_SECRET_KEY=<your project's secret key>
   export LANGFUSE_BASE_URL=<your Langfuse address>
   ```

3. Run the eight questions with both agents:

   ```bash
   python3 run_comparison.py
   ```

## Deliverables

- A completed [`symbol_index.py`](symbol_index.py).
- A completed [`symbol_server.py`](symbol_server.py), with its three tools and their descriptions, registered in [`opencode.jsonc`](opencode.jsonc) as `symbols`.
- The comparison from `run_comparison.py`, with a trace link for each run. In Langfuse, the `symbol-agent` traces show calls to your tools, such as `symbols_search_symbol` and `symbols_read_range`.
