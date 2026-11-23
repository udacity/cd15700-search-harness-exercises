"""Load and validate the harness config file."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from harness.model import ModelClient


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelSettings(Strict):
    name: str
    max_output_tokens: PositiveInt = 16000


class Limits(Strict):
    turn_cap: PositiveInt = 20
    token_budget: PositiveInt = 200_000
    retry_cap: PositiveInt = 3
    max_tool_output_bytes: PositiveInt = 20_000
    max_tool_calls: PositiveInt = 20


class Tools(Strict):
    allow: list[str] = Field(min_length=1)


class SystemPrompt(Strict):
    rules: list[str] = []

    def render(self) -> str:
        return "\n".join(f"- {rule}" for rule in self.rules)


class HarnessConfig(Strict):
    model: ModelSettings
    limits: Limits = Limits()
    tools: Tools
    system_prompt: SystemPrompt = SystemPrompt()

    def model_client(self) -> ModelClient:
        return ModelClient(
            model=self.model.name, max_output_tokens=self.model.max_output_tokens
        )


def load_config(path: Path | str) -> HarnessConfig:
    """Read and validate a YAML config file."""
    return HarnessConfig.model_validate(yaml.safe_load(Path(path).read_text()) or {})
