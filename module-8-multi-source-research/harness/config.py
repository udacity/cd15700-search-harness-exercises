"""Load and validate the harness config file, agent.yaml.

The config sets the model, the limits, the tool allow-list and the system prompt rules.
Validation reports every problem at once rather than stopping at the first one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness.model import ModelClient


class ConfigError(ValueError):
    """The config file is missing, unparseable, or invalid. Raised once, listing everything."""


@dataclass(frozen=True)
class ModelSettings:
    name: str
    max_output_tokens: int = 16000


@dataclass(frozen=True)
class Limits:
    turn_cap: int = 20
    token_budget: int = 200_000
    retry_cap: int = 3
    max_tool_output_bytes: int = 20_000
    max_tool_calls: int = 20


@dataclass(frozen=True)
class SystemPrompt:
    rules: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join(f"- {rule}" for rule in self.rules)


@dataclass(frozen=True)
class HarnessConfig:
    model: ModelSettings
    limits: Limits = field(default_factory=Limits)
    tools: list[str] = field(default_factory=list)
    system_prompt: SystemPrompt = field(default_factory=SystemPrompt)

    def model_client(self) -> ModelClient:
        """The model client. The API key comes from OPENAI_API_KEY, never from the file."""
        return ModelClient(model=self.model.name, max_output_tokens=self.model.max_output_tokens)


_SECTIONS = {
    "model": {"name", "max_output_tokens"},
    "limits": {"turn_cap", "token_budget", "retry_cap", "max_tool_output_bytes", "max_tool_calls"},
    "tools": {"allow"},
    "system_prompt": {"rules"},
}


def load_config(path: Path | str) -> HarnessConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"no config file at {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a mapping at the top level")

    problems: list[str] = []
    for name in raw:
        if name not in _SECTIONS:
            problems.append(f"unknown section {name!r}; expected one of: {', '.join(_SECTIONS)}")
    for name, allowed in _SECTIONS.items():
        section = raw.get(name)
        if isinstance(section, dict):
            problems += [f"unknown key {name}.{key!r}" for key in section if key not in allowed]

    model_section = raw.get("model") or {}
    if not model_section.get("name"):
        problems.append("model.name is required")
    limits_section = raw.get("limits") or {}
    defaults = Limits()
    limits = Limits(**{
        key: _positive(limits_section, key, getattr(defaults, key), problems)
        for key in ("turn_cap", "token_budget", "retry_cap", "max_tool_output_bytes", "max_tool_calls")
    })
    allow = (raw.get("tools") or {}).get("allow") or []
    if not isinstance(allow, list) or not allow or not all(isinstance(t, str) for t in allow):
        problems.append("tools.allow must be a non-empty list of tool names")
    rules = (raw.get("system_prompt") or {}).get("rules") or []
    if not isinstance(rules, list) or not all(isinstance(r, str) for r in rules):
        problems.append("system_prompt.rules must be a list of strings, one instruction each")

    if problems:
        raise ConfigError(f"{path} has {len(problems)} problem(s):\n" + "\n".join(f"  - {p}" for p in problems))
    return HarnessConfig(
        model=ModelSettings(
            name=str(model_section["name"]),
            max_output_tokens=_positive(model_section, "max_output_tokens", 16000, problems),
        ),
        limits=limits,
        tools=list(allow),
        system_prompt=SystemPrompt(rules=list(rules)),
    )


def _positive(section: dict[str, Any], key: str, default: int, problems: list[str]) -> int:
    value = section.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        problems.append(f"{key} must be a positive integer, got {value!r}")
        return default
    return value
