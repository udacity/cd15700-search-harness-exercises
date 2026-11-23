"""A research agent that the harness keeps predictable.

The model plans, searches and writes. The harness runs the plan, numbers every search
result as a source, checks progress after each round, decides when to stop, and checks
that every citation in the answer points to a real source.
"""

from __future__ import annotations

from typing import Any

from harness.loop import AgentLoop, RunResult
from harness.model import Message, ToolCall
from harness.tools.base import ToolError
from harness.tools.registry import ToolRegistry
from pydantic import BaseModel, Field

# TODO: write the instruction for the plan call. It should get the sub-questions the question
# needs, in the order to answer them, and stop the model from searching or answering yet.
PLAN = "Break the question into the sub-questions you need to answer, in order. Don't search yet."
# TODO: write the instruction for the reflection call. It should get the model to check the
# sources found so far against the plan: which sub-questions they answer, and what's missing.
REFLECT = (
    "Check your progress against the plan, using only the numbered sources found so far. "
    "A sub-question is answered once a source states its answer: it doesn't need every detail. "
    "Which sub-questions are answered, and what is still missing?"
)
# TODO: write the instruction for the answer call. It should ask for the final answer from the
# numbered sources only, with each claim listing the numbers of the sources that support it.
ANSWER = (
    "Write the final answer, using only the numbered sources found so far. "
    "Each claim must list the numbers of the sources that support it."
)


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
        # TODO Step 1: record the result into results
        self.results.append(output)
        # TODO Step 2: return the result's number: its position, counting from 1.
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
        self.plan = self._plan(messages)
        # TODO Step 2: search in rounds.
        # Before each round, check the budget.
        # After each one, reflect, then apply the stopping rules.
        # Record why the search stopped in stopped_by.
        self.stopped_by = "budget"
        while not self._budget_used_up():
            self._search_round(messages, schemas)
            reason = self._stop_reason(self._reflect(messages))
            if reason:
                self.stopped_by = reason
                break
        # TODO Step 3: write the final answer, and finish the run with it as text.
        # Hint: _finish(messages, text), from AgentLoop in harness/loop.py, adds the answer to the
        # conversation and returns the RunResult. render() turns an Answer into text.
        self.answer = self._final_answer(messages)
        return self._finish(messages, render(self.answer))

    def _plan(self, messages: list[Message]) -> Plan:
        """Ask the model for the plan, and add it to the conversation."""
        # TODO: ask with the PLAN instruction, the Plan schema and no tools.
        # Hint: _ask(messages, schemas, schema), from AgentLoop in harness/loop.py, makes one model
        # call and counts its tokens.
        # Hint: Make sure to add the Plan schema to get a structured output the harness can parse
        plan = self._ask(
            messages + [Message(role="user", content=PLAN)], [], Plan
        ).parsed
        # TODO: Add the plan to the conversation as numbered sub-questions, as the model's own
        # turn.
        messages.append(
            Message(
                role="assistant", content=f"My plan:\n{numbered(plan.sub_questions)}"
            )
        )
        return plan

    def _search_round(self, messages: list[Message], schemas: list[dict]) -> None:
        """One round: one model turn with the search tools, and the searches it asks for."""
        # TODO Step 1: increase the round counter.
        self.rounds += 1
        # TODO Step 2: ask the model, with the tool schemas, and add its turn, with its tool calls,
        # to the conversation.
        # Hint: _ask(messages, schemas, schema), from AgentLoop in harness/loop.py, makes one model
        # call and counts its tokens.
        response = self._ask(messages, schemas)
        messages.append(
            Message(
                role="assistant",
                content=response.text or "",
                tool_calls=tuple(response.tool_calls),
            )
        )
        # TODO Step 3: run each tool call with _execute_within_budget, and add every result to
        # the conversation.
        for call in response.tool_calls:
            messages.append(self._execute_within_budget(call))

    def _reflect(self, messages: list[Message]) -> Reflection:
        """Ask which sub-questions the sources answer so far."""
        # TODO Step 1: ask with the REFLECT instruction, the Reflection schema and no tools.
        # Hint: Make sure to add the Reflection schema to get a structured output the harness can parse
        reflection = self._ask(
            messages + [Message(role="user", content=REFLECT)], [], Reflection
        ).parsed
        # TODO Step 2: keep the answered numbers that are in the plan, in self.answered, and set
        # self.progressed if this round answered a sub-question that wasn't answered before.
        answered = {
            n for n in reflection.answered if 1 <= n <= len(self.plan.sub_questions)
        }
        self.progressed = bool(answered - self.answered)
        self.answered = answered
        # TODO Step 3: tell the model what's still missing, as a user message, so the next round
        # searches for it.
        messages.append(
            Message(
                role="user",
                content=f"Still missing: {'; '.join(reflection.missing) or 'nothing'}.",
            )
        )
        return reflection

    def _stop_reason(self, reflection: Reflection) -> str | None:
        """Why the search should stop now, or None to keep going."""
        # TODO Step 1: "sufficient" when the reflection says so and every sub-question is answered.
        if reflection.sufficient and len(self.answered) == len(self.plan.sub_questions):
            return "sufficient"
        # TODO Step 2: "stalled" when two rounds in a row made no progress.
        self.rounds_without_progress = (
            0 if self.progressed else self.rounds_without_progress + 1
        )
        if self.rounds_without_progress >= 2:
            return "stalled"
        return None

    def _final_answer(self, messages: list[Message]) -> Answer:
        """The final answer, with every citation checked."""
        # TODO Step 1: start from the ANSWER instruction. If the search stopped before every
        # sub-question was answered, add the open ones, for the model to list as gaps.
        instruction = ANSWER
        open_questions = [
            q
            for n, q in enumerate(self.plan.sub_questions, start=1)
            if n not in self.answered
        ]
        if open_questions:
            instruction += " List these as gaps: " + "; ".join(open_questions)
        # TODO Step 2: ask with that instruction, the Answer schema and no tools.
        # Hint: Make sure to add the Answer schema to get a structured output the harness can parse
        answer = self._ask(
            messages + [Message(role="user", content=instruction)], [], Answer
        ).parsed

        # TODO Step 3: check every cited number with Sources.is_valid. Count the citations,
        # and the valid ones, in citation_check.
        cited = [n for claim in answer.claims for n in claim.sources]
        self.citation_check = (len(cited), sum(self.sources.is_valid(n) for n in cited))

        # TODO Step 4: drop the numbers that aren't real sources, and the claims left with none.
        claims = [
            Claim(text=c.text, sources=valid)
            for c in answer.claims
            if (valid := [n for n in c.sources if self.sources.is_valid(n)])
        ]
        return Answer(claims=claims, gaps=answer.gaps)

    def _budget_used_up(self) -> bool:
        """Whether the search budget has run out."""
        # TODO: the budget has run out once the searches reach max_tool_calls, or the tokens,
        # input and output together, reach token_budget minus TOKEN_RESERVE.
        used = self.input_tokens + self.output_tokens
        return (
            sum(self.searches.values()) >= self._max_tool_calls
            or used >= self._token_budget - TOKEN_RESERVE
        )

    def _execute_within_budget(self, call: ToolCall) -> Message:
        """Run one search, unless the budget has no searches left."""
        # TODO Step 1: if max_tool_calls searches have already run, skip this search, and return a
        # tool message saying the search budget is used up, marked is_error.
        # Hint: ToolError(message, hint).as_payload() formats the error the way the model expects.
        if sum(self.searches.values()) >= self._max_tool_calls:
            error = ToolError(
                "search budget used up", hint="no more searches in this run"
            )
            return Message(
                role="tool",
                content=error.as_payload(),
                tool_call_id=call.id,
                is_error=True,
            )
        # TODO Step 2: count the search in self.searches, by tool name, then run it.
        # Hint: self._execute(call), from AgentLoop in harness/loop.py, runs the tool, turns a
        # ToolError into an error message for the model, and traces the call in Langfuse.
        self.searches[call.name] = self.searches.get(call.name, 0) + 1
        return self._execute(call)


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
