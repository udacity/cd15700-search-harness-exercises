"""The agent loop.

Send the transcript to the model, run the tool calls it asks for, add the results to the
transcript, and repeat until the model gives a final answer or a limit is hit. A limit
raises rather than returning a partial result, so a run that never answered cannot pass
for one that did.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from langfuse import get_client

from harness.events import EventLog
from harness.model import Message, ModelClient, ToolCall
from harness.tools.base import ToolError
from harness.tools.registry import ToolRegistry


class RunAborted(RuntimeError):
    """Base for the ways a run can stop without answering."""

    outcome = "aborted"


class TurnCapExceeded(RunAborted):
    """The model was still calling tools when the turn cap was reached."""

    outcome = "turn_cap"

    def __init__(self, turn_cap: int) -> None:
        super().__init__(f"turn cap of {turn_cap} exceeded without a final answer")
        self.turn_cap = turn_cap


class RetryCapExceeded(RunAborted):
    """Too many tool calls failed in a row. A successful call resets the count."""

    outcome = "retry_cap"

    def __init__(self, retry_cap: int, last_error: str) -> None:
        super().__init__(
            f"{retry_cap} tool calls failed in a row without a success; last error: {last_error}"
        )
        self.retry_cap = retry_cap
        self.last_error = last_error


class BudgetExhausted(RunAborted):
    """The token budget ran out mid-run."""

    outcome = "budget_exhausted"

    def __init__(self, token_budget: int, used: int) -> None:
        super().__init__(f"token budget of {token_budget} exhausted after {used} tokens")
        self.token_budget = token_budget
        self.used = used


@dataclass
class RunResult:
    """A finished run: the final answer, the transcript, and the token totals."""

    final_text: str
    turns: int
    messages: list[Message] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    # The run's Langfuse trace, to link to it. None when Langfuse is off.
    trace_id: str | None = None


class AgentLoop:
    """Runs one task to completion, or to a limit."""

    def __init__(
        self,
        client: ModelClient,
        registry: ToolRegistry,
        turn_cap: int = 40,
        system_prompt: str | None = None,
        retry_cap: int = 3,
        token_budget: int = 200_000,
        events: EventLog | None = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._turn_cap = turn_cap
        self._system_prompt = system_prompt
        self._retry_cap = retry_cap
        self._token_budget = token_budget
        self._events = events
        self._consecutive_failures = 0

    def run(self, task: str) -> RunResult:
        """Run ``task`` to a final answer, or raise a ``RunAborted`` when a limit is hit.

        The whole run is one Langfuse trace: the model calls and tool calls nest under it.
        """
        with get_client().start_as_current_observation(name="research-question", as_type="agent", input=task) as trace:
            try:
                result = self._run(task)
            except RunAborted as exc:
                trace.update(level="ERROR", status_message=str(exc))
                raise
            trace.update(output=result.final_text)
            return replace(result, trace_id=trace.trace_id)

    def _run(self, task: str) -> RunResult:
        messages: list[Message] = []

        if self._system_prompt:
            messages.append(Message(role="system", content=self._system_prompt))
        messages.append(Message(role="user", content=task))

        schemas = self._registry.schemas()
        self._consecutive_failures = 0
        turns = 0
        input_tokens = 0
        output_tokens = 0

        self._emit(
            "session_start",
            task=task,
            model=self._client.model,
            tools=self._registry.names(),
            turn_cap=self._turn_cap,
            retry_cap=self._retry_cap,
            token_budget=self._token_budget,
            session_dir=str(self._events.session_dir) if self._events else None,
        )

        try:
            while turns < self._turn_cap:
                started = time.monotonic()
                response = self._client.complete(messages, schemas)
                turns += 1
                input_tokens += response.input_tokens
                output_tokens += response.output_tokens

                self._emit(
                    "model_call",
                    turn=turns,
                    model=self._client.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    duration_ms=_ms_since(started),
                    tool_calls=[c.name for c in response.tool_calls],
                    finished=response.is_final,
                )

                if response.is_final:
                    messages.append(Message(role="assistant", content=response.text or ""))
                    result = RunResult(
                        final_text=response.text or "",
                        turns=turns,
                        messages=messages,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    self._emit_end("final_answer", result)
                    return result

                messages.append(
                    Message(
                        role="assistant",
                        content=response.text or "",
                        tool_calls=tuple(response.tool_calls),
                    )
                )
                for call in response.tool_calls:
                    messages.append(self._execute(call, turns))

                used = input_tokens + output_tokens
                if used >= self._token_budget:
                    raise BudgetExhausted(self._token_budget, used)

            raise TurnCapExceeded(self._turn_cap)
        except RunAborted as exc:
            self._emit_end(
                exc.outcome,
                RunResult("", turns, messages, input_tokens, output_tokens),
                error=str(exc),
            )
            raise

    def _execute(self, call: ToolCall, turn: int) -> Message:
        """Run one tool call and return its result message.

        A failing tool becomes an error result the model can read rather than an
        exception, until failures in a row reach the retry cap: that one raises.
        """
        self._emit(
            "tool_call", turn=turn, call_id=call.id, tool=call.name, arguments=call.arguments
        )
        with get_client().start_as_current_observation(name=call.name, as_type="tool", input=call.arguments) as span:
            message = self._run_tool(call, turn)
            span.update(output=message.content, level="ERROR" if message.is_error else "DEFAULT")
            return message

    def _run_tool(self, call: ToolCall, turn: int) -> Message:
        started = time.monotonic()

        try:
            output = self._registry.call(call.name, call.arguments)
        except ToolError as exc:
            self._consecutive_failures += 1
            payload = exc.as_payload()
            self._emit(
                "tool_result",
                turn=turn,
                call_id=call.id,
                tool=call.name,
                ok=False,
                error=str(exc),
                output_bytes=len(payload.encode()),
                duration_ms=_ms_since(started),
                consecutive_failures=self._consecutive_failures,
            )
            if self._consecutive_failures >= self._retry_cap:
                raise RetryCapExceeded(self._retry_cap, str(exc)) from exc
            # Fed back to the model as a result, so it can read the hint and try again.
            return Message(role="tool", content=payload, tool_call_id=call.id, is_error=True)

        self._consecutive_failures = 0
        self._emit(
            "tool_result",
            turn=turn,
            call_id=call.id,
            tool=call.name,
            ok=True,
            output_bytes=len(output.encode()),
            duration_ms=_ms_since(started),
            consecutive_failures=0,
        )
        return Message(role="tool", content=output, tool_call_id=call.id)

    def _emit(self, event: str, **fields: object) -> None:
        if self._events is not None:
            self._events.emit(event, **fields)

    def _emit_end(self, outcome: str, result: RunResult, error: str | None = None) -> None:
        if self._events is None:
            return
        self._events.emit(
            "session_end",
            outcome=outcome,
            turns=result.turns,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=self._events.elapsed_ms(),
            error=error,
        )


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
