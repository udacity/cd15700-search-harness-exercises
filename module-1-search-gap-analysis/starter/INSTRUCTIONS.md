# Build a Search Gap Analysis from Five Baseline Tasks

An invoicing assistant for a small business can search the code and documentation of its bookkeeping software, and nothing else. Five teams have each brought it a question that needs a source outside that codebase. Your job is to measure where the agent breaks and name the search type that would fix each failure.

## Exercise structure

- [`baseline_tasks.yaml`](baseline_tasks.yaml): the five tasks, with each team's question, the source it needs and its expected answer.
- [`run_baseline.py`](run_baseline.py): runs the five tasks through the agent and grades each run.
- [`shared/agent_runs.py`](../../shared/agent_runs.py): the functions that run the agent and find its trace.
- [`opencode.jsonc`](opencode.jsonc) and [`.opencode/agents/baseline-agent.md`](.opencode/agents/baseline-agent.md): the agent's configuration.
- [`setup_codebase.sh`](setup_codebase.sh): clones the codebase, [python-accounting](https://github.com/ekmungai/python-accounting), at a pinned commit.

## Tasks

1. **Understand the baseline tasks.** Read each task in [`baseline_tasks.yaml`](baseline_tasks.yaml), and why it needs a source outside the codebase.
2. **Trace the agent.** Configure [`opencode.jsonc`](opencode.jsonc) so every run sends a trace to Langfuse. Pin Langfuse's plugin to version 0.5.2. See Langfuse's [OpenCode integration](https://langfuse.com/integrations/developer-tools/opencode) guide and OpenCode's [plugins](https://opencode.ai/v2/docs/plugins) documentation.
3. **Grade each run.** Complete `grade` in [`run_baseline.py`](run_baseline.py). A run passes only when it's both:
   - **Correct:** the answer contains every fact in the task's `correct_if` patterns.
   - **Grounded:** each of those facts also appears in the output of a tool call that completed.
4. **Classify each failure.** Open each failed run's trace in Langfuse, and decide which search type would have resolved it. Record it as an annotation on the trace, named `missing_search_type`, with one of the categories `web`, `semantic`, `document`, `memory`, `api` and `codebase`. See Langfuse's [annotation](https://langfuse.com/docs/evaluation/evaluation-methods/annotation) documentation.

> **Important:** don't change the agent's permissions or prompt. The point is to measure the agent as it is.

## Set up and run

1. Clone the codebase the agent searches, into `python-accounting/`:

   ```bash
   bash setup_codebase.sh
   ```

2. Set your keys for the model and for your Langfuse project:

   ```bash
   export OPENAI_API_KEY=<your key>
   export OPENAI_BASE_URL=<your base URL>
   export LANGFUSE_PUBLIC_KEY=<your project's public key>
   export LANGFUSE_SECRET_KEY=<your project's secret key>
   export LANGFUSE_BASE_URL=<your Langfuse address>
   ```

3. Run the five tasks:

   ```bash
   python3 run_baseline.py
   ```

## Deliverables

- A completed [`run_baseline.py`](run_baseline.py) that runs all five tasks, grades each run and links it to its Langfuse trace.
- In Langfuse, each failed run's trace annotated with its missing search type.
