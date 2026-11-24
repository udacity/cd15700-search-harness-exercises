"""A research agent that the harness keeps predictable.

The model plans, searches and writes. The harness runs the plan, numbers every search
result as a source, checks progress after each round, decides when to stop, and checks
that every citation in the answer points to a real source.
"""

from __future__ import annotations

from typing import Any

from harness.loop import AgentLoop, RunResult
from harness.model import Message, ToolCall
from harness.tools.registry import ToolRegistry
from pydantic import BaseModel, Field

# TODO: write the instruction for the plan call. It should get the sub-questions the question
# needs, in the order to answer them, and stop the model from searching or answering yet.
PLAN = ""
# TODO: write the instruction for the reflection call. It should get the model to check the
# sources found so far against the plan: which sub-questions they answer, and what's missing.
REFLECT = ""
# TODO: write the instruction for the answer call. It should ask for the final answer from the
# numbered sources only, with each claim listing the numbers of the sources that support it.
ANSWER = ""


# The tokens kept back when deciding whether to start another round: enough for that round,
# its reflection and the final answer, so the whole run stays within token_budget.
TOKEN_RESERVE = 25_000


# The structured answers the harness asks the model for.
class Plan(BaseModel):
    sub_questions: list[str] = Field(
        min_length=1, description="The sub-questions, in the order to answer them."
    )


class Reflection(BaseModel):
    answered: list[int] = Field(
        description="The numbers of the sub-questions the sources answer."
    )
    missing: list[str] = Field(description="What the sources don't answer yet.")
    sufficient: bool = Field(
        description="Whether the sources answer every sub-question."
    )


class Claim(BaseModel):
    text: str
    sources: list[int] = Field(
        min_length=1, description="The numbers of the sources that support the claim."
    )


class Answer(BaseModel):
    claims: list[Claim]
    gaps: list[str] = Field(description="What the answer couldn't cover.")


class Sources:
    """Every search result in this run, numbered from 1."""

    def __init__(self) -> None:
        self.results: list[str] = []

    def add(self, output: str) -> int:
        """Record one search result, and return its number."""
        self.results.append(output)
        return len(self.results)

    def is_valid(self, number: int) -> bool:
        return 1 <= number <= len(self.results)


class Numbered:
    """A search tool whose results are recorded as numbered sources. Each result starts
    with its number, like [3], so the model knows how to cite it."""

    def __init__(self, tool: Any, sources: Sources) -> None:
        self._tool, self._sources = tool, sources
        self.name, self.description, self.Args = tool.name, tool.description, tool.Args

    def call(self, args: BaseModel) -> str:
        output = self._tool.call(args)
        return f"[{self._sources.add(output)}] {output}"


class ResearchLoop(AgentLoop):
    """Plan, then search in rounds, with a check after each one, then answer.

    A round is one model turn with its searches. The search stops when
    - the reflection says every sub-question is answered
    - when two rounds in a row answer no new sub-question
    - when the budget runs out: max_tool_calls searches, or token_budget tokens.
    """

    def __init__(
        self, *args: Any, sources: Sources, max_tool_calls: int, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.sources = sources
        self._max_tool_calls = max_tool_calls

    def _run(self, task: str) -> RunResult:
        # The conversation sent to the model, from AgentLoop._start in harness/loop.py: the
        # system prompt and the question. Each step below adds to it.
        messages = self._start(task)
        # The search tools' names, descriptions and argument schemas, from ToolRegistry in
        # harness/tools/registry.py.
        schemas = self._registry.schemas()

        self.searches: dict[str, int] = {}
        self.rounds = self.rounds_without_progress = 0
        self.answered: set[int] = set()

        # TODO Step 1: get the plan.
        self.plan = ...
        # Search in rounds, until the budget runs out or a stopping rule ends the search.
        self.stopped_by = "budget"
        while not self._budget_used_up():
            # TODO Step 2: run one search round.
            # TODO Step 3: reflect, then apply the stopping rules. When one of them ends the search,
            # record why in stopped_by, and stop.
            raise NotImplementedError
        # TODO Step 4: write the final answer.
        self.answer = ...
        # TODO Step 5: finish the run with the answer as text.
        # Hint: _finish(messages, text), from AgentLoop in harness/loop.py, adds the answer to the
        # conversation and returns the RunResult. render() turns an Answer into text.
        result = ...
        return result

    def _plan(self, messages: list[Message]) -> Plan:
        """Ask the model for the plan, and add it to the conversation."""
        # TODO Step 1: ask with the PLAN instruction, the Plan schema and no tools.
        # Hint: _ask(messages, schemas, schema), from AgentLoop in harness/loop.py, makes one model
        # call and counts its tokens.
        # Hint: pass the Plan schema, so the harness gets a structured answer it can parse.
        plan = ...
        # TODO Step 2: add the plan to the conversation as numbered sub-questions, as the
        # model's own turn.
        return plan

    def _search_round(self, messages: list[Message], schemas: list[dict]) -> None:
        """One round: one model turn with the search tools, and the searches it asks for."""
        # TODO Step 1: increase the round counter.

        # TODO Step 2: ask the model, with the tool schemas, and add its turn, with its tool calls,
        # to the conversation.
        # Hint: _ask(messages, schemas, schema), from AgentLoop in harness/loop.py, makes one model
        # call and counts its tokens. Pass tool_choice="required", so the model has to search: a
        # round without a search can't make progress.
        response = ...
        # TODO Step 3: run each tool call with _execute_within_budget, and add every result to
        # the conversation.
        raise NotImplementedError

    def _reflect(self, messages: list[Message]) -> Reflection:
        """Ask which sub-questions the sources answer so far."""
        # TODO Step 1: ask with the REFLECT instruction, the Reflection schema and no tools.
        # Hint: pass the Reflection schema, so the harness gets a structured answer it can parse.
        reflection = ...
        # TODO Step 2: keep the answered numbers that are in the plan, in self.answered, and set
        # self.progressed if this round answered a sub-question that wasn't answered before.
        answered = ...
        self.progressed = ...
        self.answered = answered
        # TODO Step 3: tell the model what's still missing, as a user message, so the next round
        # searches for it.
        return reflection

    def _stop_reason(self, reflection: Reflection) -> str | None:
        """Why the search should stop now, or None to keep going."""
        # TODO Step 1: "sufficient" when the reflection says so and every sub-question is answered.
        # TODO Step 2: "stalled" when two rounds in a row made no progress.
        raise NotImplementedError

    def _final_answer(self, messages: list[Message]) -> Answer:
        """The final answer, with every citation checked."""
        # TODO Step 1: start from the ANSWER instruction. If the search stopped before every
        # sub-question was answered, add the open ones, for the model to list as gaps.
        instruction = ANSWER
        # TODO Step 2: ask with that instruction, the Answer schema and no tools.
        # Hint: pass the Answer schema, so the harness gets a structured answer it can parse.
        answer = ...
        # TODO Step 3: check every cited number with Sources.is_valid. Count the citations,
        # and the valid ones, in citation_check, as a pair: (5, 4) means 5 citations, 4 valid.
        self.citation_check = ...
        # TODO Step 4: drop the numbers that aren't real sources, and the claims left with none.
        claims = ...
        return Answer(claims=claims, gaps=answer.gaps)

    def _budget_used_up(self) -> bool:
        """Whether the search budget has run out."""
        # TODO: the budget has run out once the searches reach max_tool_calls, or the tokens,
        # input and output together, reach token_budget minus TOKEN_RESERVE.
        raise NotImplementedError

    def _execute_within_budget(self, call: ToolCall) -> Message:
        """Run one search, unless the budget has no searches left."""
        # TODO Step 1: if max_tool_calls searches have already run, skip this search, and return a
        # tool message saying the search budget is used up, marked is_error.
        # Hint: ToolError(message, hint).as_payload() formats the error the way the model expects.
        # TODO Step 2: count the search in self.searches, by tool name, then run it.
        # Hint: self._execute(call), from AgentLoop in harness/loop.py, runs the tool, turns a
        # ToolError into an error message for the model, and traces the call in Langfuse.
        raise NotImplementedError


def numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))


def render(answer: Answer) -> str:
    """The answer as text: each claim with its sources, then the gaps."""
    lines = [
        f"- {c.text} {''.join(f'[{n}]' for n in c.sources)}" for c in answer.claims
    ]
    if answer.gaps:
        lines += ["", "Gaps:"] + [f"- {gap}" for gap in answer.gaps]
    return "\n".join(lines)


def build_loop(config, search_tools: list[Any]) -> ResearchLoop:
    """A ResearchLoop over the given search tools, with the config's model and limits."""
    sources = Sources()
    registry = ToolRegistry([Numbered(tool, sources) for tool in search_tools])
    return ResearchLoop.from_config(
        config, registry, sources=sources, max_tool_calls=config.limits.max_tool_calls
    )
