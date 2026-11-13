"""The model client, and the message types the agent loop works with.

Calls the Chat Completions API through the OpenAI SDK. The SDK reads OPENAI_API_KEY and
OPENAI_BASE_URL from the environment. It's Langfuse's drop-in wrapper of the SDK, so every
model call is traced, with its tokens and cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import openai
from langfuse.openai import OpenAI


class ModelError(RuntimeError):
    """The endpoint could not be reached, or answered with something unusable."""


class TruncatedResponse(ModelError):
    """The model hit its output limit mid-answer. Raise max_output_tokens: retrying won't help."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str | None = None
    is_error: bool = False
    # The tool calls an assistant turn made. They must stay in the transcript: the
    # endpoint rejects a tool result whose call id it has not seen.
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ModelResponse:
    """One model turn: either text, or tool calls, or both."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def is_final(self) -> bool:
        return not self.tool_calls


class ModelClient:
    def __init__(self, model: str, max_output_tokens: int = 16000, client: OpenAI | None = None) -> None:
        # Logged with every call, so token counts can be priced per model.
        self.model = model
        self._max_output_tokens = max_output_tokens
        self._client = client or OpenAI()

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [_wire_message(m) for m in messages],
            # Reasoning models count their reasoning against this limit too.
            "max_completion_tokens": self._max_output_tokens,
        }
        if tools:
            request["tools"] = [
                {"type": "function",
                 "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
                for t in tools
            ]
        try:
            response = self._client.chat.completions.create(**request)
        except openai.OpenAIError as exc:
            raise ModelError(f"{self.model} call failed: {exc}") from exc

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise TruncatedResponse(f"{self.model} hit the {self._max_output_tokens}-token output limit")
        calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=_decode_arguments(call.function.arguments))
            for call in choice.message.tool_calls or []
        ]
        return ModelResponse(
            text=choice.message.content,
            tool_calls=calls,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )


def _wire_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        # Send the calls this turn made; the tool results that follow refer to them by id.
        wire["tool_calls"] = [
            {"id": call.id, "type": "function",
             "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
            for call in message.tool_calls
        ]
    return wire


def _decode_arguments(raw: object) -> dict[str, Any]:
    """Decode a tool call's arguments, which arrive as a JSON string and may be invalid."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        decoded = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise ModelError(f"model emitted unparseable tool arguments: {raw!r}") from exc
    if not isinstance(decoded, dict):
        raise ModelError(f"tool arguments were {type(decoded).__name__}, expected an object")
    return decoded
