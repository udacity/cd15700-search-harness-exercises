"""The agent loop: call the model, run the tool calls it asks for, and repeat until it
answers or a limit is hit."""

from __future__ import annotations

from harness.config import HarnessConfig
from harness.model import Message, ModelClient, ModelResponse, ToolCall
from harness.tools.base import ToolError, truncate
from harness.tools.registry import ToolRegistry
from langfuse import get_client
from pydantic import BaseModel


class RunAborted(RuntimeError):
    """The run stopped without a final answer: a limit was hit."""


class RunResult(BaseModel):
    """A finished run: the final answer, the transcript, and the token totals."""

    final_text: str
    turns: int
    messages: list[Message] = []
    input_tokens: int = 0
    output_tokens: int = 0
    trace_id: str | None = None


class AgentLoop:
    """Runs one task to a final answer, or to a limit."""

    def __init__(
        self,
        client: ModelClient,
        registry: ToolRegistry,
        system_prompt: str = "",
        turn_cap: int = 20,
        token_budget: int = 200_000,
        retry_cap: int = 3,
        max_tool_output_bytes: int = 20_000,
    ) -> None:
        self._client = client
        self._registry = registry
        self._system_prompt = system_prompt
        self._turn_cap = turn_cap
        self._token_budget = token_budget
        self._retry_cap = retry_cap
        self._max_tool_output_bytes = max_tool_output_bytes

    @classmethod
    def from_config(
        cls, config: HarnessConfig, registry: ToolRegistry, **extra
    ) -> AgentLoop:
        """A loop with the config's model, system prompt and limits."""
        return cls(
            config.model_client(),
            registry,
            system_prompt=config.system_prompt.render(),
            turn_cap=config.limits.turn_cap,
            token_budget=config.limits.token_budget,
            retry_cap=config.limits.retry_cap,
            max_tool_output_bytes=config.limits.max_tool_output_bytes,
            **extra,
        )

    def run(self, task: str) -> RunResult:
        """Run the task to a final answer, or raise RunAborted when a limit is hit."""
        with get_client().start_as_current_observation(
            name="research-question", as_type="agent", input=task
        ) as trace:
            try:
                result = self._run(task)
            except RunAborted as exc:
                trace.update(level="ERROR", status_message=str(exc))
                raise
            trace.update(output=result.final_text)
            return result.model_copy(update={"trace_id": trace.trace_id})

    def _run(self, task: str) -> RunResult:
        messages = self._start(task)
        schemas = self._registry.schemas()
        while self.turns < self._turn_cap:
            response = self._ask(messages, schemas)
            if response.is_final:
                return self._finish(messages, response.text)
            messages.append(
                Message(
                    role="assistant",
                    content=response.text or "",
                    tool_calls=tuple(response.tool_calls),
                )
            )
            for call in response.tool_calls:
                messages.append(self._execute(call))
            if self.input_tokens + self.output_tokens >= self._token_budget:
                raise RunAborted(
                    f"token budget of {self._token_budget} used up without a final answer"
                )
        raise RunAborted(f"turn cap of {self._turn_cap} reached without a final answer")

    def _start(self, task: str) -> list[Message]:
        """Reset the counters and start the transcript."""
        self.turns = self.input_tokens = self.output_tokens = 0
        self._failures_in_a_row = 0
        messages = (
            [Message(role="system", content=self._system_prompt)]
            if self._system_prompt
            else []
        )
        return messages + [Message(role="user", content=task)]

    def _ask(
        self,
        messages: list[Message],
        schemas: list[dict],
        schema: type[BaseModel] | None = None,
        tool_choice: str | None = None,
    ) -> ModelResponse:
        """One model call, counted. With a schema, the answer is in ``response.parsed``.
        With tool_choice="required", the model must call a tool."""
        response = self._client.complete(messages, schemas, schema, tool_choice)
        self.turns += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        return response

    def _execute(self, call: ToolCall) -> Message:
        """Run one tool call. A failure goes back to the model as an error, up to the retry cap."""
        with get_client().start_as_current_observation(
            name=call.name, as_type="tool", input=call.arguments
        ) as span:
            try:
                output = truncate(
                    self._registry.call(call.name, call.arguments),
                    self._max_tool_output_bytes,
                )
            except ToolError as exc:
                self._failures_in_a_row += 1
                span.update(output=exc.as_payload(), level="ERROR")
                if self._failures_in_a_row >= self._retry_cap:
                    raise RunAborted(
                        f"{self._retry_cap} tool calls failed in a row; last: {exc.message}"
                    ) from exc
                return Message(
                    role="tool",
                    content=exc.as_payload(),
                    tool_call_id=call.id,
                    is_error=True,
                )
            self._failures_in_a_row = 0
            span.update(output=output)
            return Message(role="tool", content=output, tool_call_id=call.id)

    def _finish(self, messages: list[Message], text: str | None) -> RunResult:
        """The final answer and the transcript."""
        messages.append(Message(role="assistant", content=text or ""))
        return RunResult(
            final_text=text or "",
            turns=self.turns,
            messages=messages,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )
