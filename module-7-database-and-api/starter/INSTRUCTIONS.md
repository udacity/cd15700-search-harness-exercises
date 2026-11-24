# Answer Multi-Source Questions with NL Query Translation

A company's finance team asks an agent questions about its ledger, like how much a client still owes, or a month's invoices converted to euros. The agent answers by writing SQL against the ledger, and by looking up exchange rates from an API. Both are risky: the model writes the SQL, so a bad query could change the ledger or run forever, and an agent in a loop could flood the rates API.

Your job is to make two MCP servers safe: the ledger server, so the agent can only read and every query is bounded, and the rates server, so it can't call the API faster than allowed. Then you'll measure how accurate, fast and costly the agent is on ten questions.

The data is built for this exercise:

- **The ledger:** [`ledger.db`](../data/ledger.db), a SQLite database of a fictional company's clients, suppliers, invoices, payments and bills, made with the [python-accounting](https://github.com/ekmungai/python-accounting) library.
- **Questions:** 10, in [`questions.json`](../data/questions.json), each with its expected answer. Six need only the ledger, and four also need an exchange rate.
- **Exchange rates:** from the [Frankfurter API](https://frankfurter.dev).

## Exercise structure

- [`ledger_server.py`](ledger_server.py): the ledger's MCP server, with two tools, `get_schema` and `run_query`, and the checks behind them.
- [`rates_server.py`](rates_server.py): the exchange-rate MCP server, with the `get_rate` tool, its rate limiter and its cache.
- [`evaluate.py`](evaluate.py): runs the ten questions through the agent, then reports accuracy, latency, tool calls and cost per question, and checks that the ledger wasn't changed.
- [`opencode.jsonc`](opencode.jsonc): the agent configuration. It registers the two servers as `ledger` and `rates`.
- [`.opencode/agents/finance-agent.md`](.opencode/agents/finance-agent.md): the agent's system prompt.
- [`shared/agent_runs.py`](../../shared/agent_runs.py): the functions that run the agent.

## Tasks

1. **Keep the ledger read-only.** In [`ledger_server.py`](ledger_server.py), complete `authorize`, which lets a query read only the tables in `ALLOWED_TABLES`, and `check_statement`, which refuses anything but a single read query before it reaches the database.
2. **Prune the schema.** Complete `tables_for` and `get_schema`, so the model reads only the tables a question needs. Write `get_schema`'s tool description.
3. **Bound every query.** Complete `limit_time`, which stops a query that runs longer than `TIMEOUT_S`, and `fetch_capped`, which returns at most `MAX_ROWS` rows, with a notice when there were more.
4. **Allow one corrected retry.** Complete `as_retry` and `run_query`, and write `run_query`'s tool description. A failed query comes back to the model with an error it can act on, and it gets `MAX_RETRIES` chances to correct its query before it has to stop.
5. **Limit and cache the API calls.** In [`rates_server.py`](rates_server.py), complete the `TokenBucket` rate limiter and `get_rate`, which answers a rate it already has from its cache, without calling the API.
6. **Evaluate.** Run [`evaluate.py`](evaluate.py).

> **Important:** don't change the agent's prompt or the ledger. The evaluation checks that the ledger is unchanged.

## Set up and run

1. Set your keys for the model:

   ```bash
   export OPENAI_API_KEY=<your key>
   export OPENAI_BASE_URL=<your base URL>
   ```

2. Run the ten questions:

   ```bash
   python3 evaluate.py
   ```

## Deliverables

- A completed [`ledger_server.py`](ledger_server.py) and [`rates_server.py`](rates_server.py).
- The output of `evaluate.py`: at least 8 of the 10 questions right, and the ledger unchanged.
