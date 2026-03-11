"""Data loading, parsing, aggregation, and cost calculation for claude-spend."""

from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

# Pricing in $/MTok
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
}

FALLBACK_MODEL = "claude-sonnet-4-6"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_write_tokens + self.cache_read_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass
class SessionMeta:
    session_id: str = ""
    project_path: str = ""
    project_name: str = ""
    start_time: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    duration_minutes: int = 0
    first_prompt: str = ""
    tool_counts: dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0


def _parse_start_time(time_str: str) -> datetime:
    """Parse ISO 8601 timestamp to datetime."""
    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))


def _project_name_from_path(path: str) -> str:
    """Extract short project name from full path. '/Users/foo/code/bar' -> 'bar'."""
    return os.path.basename(path.rstrip("/")) or path


def load_session_metas(claude_dir: str, days: int | None = 30) -> list[SessionMeta]:
    """Load session metadata files, optionally filtered to last N days."""
    meta_dir = os.path.join(claude_dir, "usage-data", "session-meta")
    if not os.path.isdir(meta_dir):
        return []

    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    results = []
    for path in glob.glob(os.path.join(meta_dir, "*.json")):
        try:
            with open(path) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        start_time = _parse_start_time(raw.get("start_time", "1970-01-01T00:00:00Z"))
        if cutoff and start_time < cutoff:
            continue

        results.append(SessionMeta(
            session_id=raw["session_id"],
            project_path=raw.get("project_path", ""),
            project_name=_project_name_from_path(raw.get("project_path", "")),
            start_time=start_time,
            duration_minutes=raw.get("duration_minutes", 0),
            first_prompt=raw.get("first_prompt", ""),
            tool_counts=raw.get("tool_counts", {}),
            input_tokens=raw.get("input_tokens", 0),
            output_tokens=raw.get("output_tokens", 0),
        ))

    results.sort(key=lambda s: s.start_time, reverse=True)
    return results


@dataclass
class SubagentCall:
    session_id: str = ""
    subagent_type: str = ""
    description: str = ""
    model: str = "unknown"
    usage: TokenUsage = field(default_factory=TokenUsage)
    duration_ms: int = 0
    tool_use_count: int = 0


@dataclass
class ConversationData:
    usage_by_model: dict[str, TokenUsage] = field(default_factory=dict)
    subagent_calls: list[SubagentCall] = field(default_factory=list)
    skill_invocations: list[str] = field(default_factory=list)
    parse_errors: int = 0


def parse_conversation_jsonl(jsonl_path: str) -> ConversationData:
    """Parse a conversation JSONL file, extracting per-model usage, subagent calls, and skills."""
    data = ConversationData()

    if not os.path.isfile(jsonl_path):
        return data

    task_calls: dict[str, dict] = {}       # tool_use_id -> {subagent_type, description, model_param}
    subagent_models: dict[str, str] = {}   # parentToolUseID -> model from progress

    lines = []
    with open(jsonl_path) as f:
        for line in f:
            try:
                msg = json.loads(line)
                lines.append(msg)
            except json.JSONDecodeError:
                data.parse_errors += 1

    for msg in lines:
        msg_type = msg.get("type")

        if msg_type == "assistant":
            inner = msg.get("message", {})
            model = inner.get("model")
            usage_raw = inner.get("usage", {})
            if model and usage_raw:
                usage = TokenUsage(
                    input_tokens=usage_raw.get("input_tokens", 0),
                    output_tokens=usage_raw.get("output_tokens", 0),
                    cache_write_tokens=usage_raw.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
                )
                if model in data.usage_by_model:
                    data.usage_by_model[model] = data.usage_by_model[model] + usage
                else:
                    data.usage_by_model[model] = usage

            for block in inner.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") == "Task":
                    inp = block.get("input", {})
                    task_calls[block["id"]] = {
                        "subagent_type": inp.get("subagent_type", "unknown"),
                        "description": inp.get("description", ""),
                        "model_param": inp.get("model"),
                    }
                elif block.get("name") == "Skill":
                    skill_name = block.get("input", {}).get("skill", "")
                    if skill_name:
                        data.skill_invocations.append(skill_name)

        elif msg_type == "progress":
            parent_id = msg.get("parentToolUseID")
            if parent_id and parent_id not in subagent_models:
                inner_data = msg.get("data", {})
                inner_msg = inner_data.get("message", {})
                if isinstance(inner_msg, dict):
                    nested = inner_msg.get("message", {})
                    if isinstance(nested, dict) and "model" in nested:
                        subagent_models[parent_id] = nested["model"]

        elif msg_type == "user":
            result = msg.get("toolUseResult")
            if not isinstance(result, dict) or "totalTokens" not in result:
                continue

            tool_use_id = None
            user_msg = msg.get("message", {})
            for block in user_msg.get("content", []) if isinstance(user_msg, dict) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    break

            if tool_use_id and tool_use_id in task_calls:
                call_info = task_calls[tool_use_id]
                usage_raw = result.get("usage", {})
                model = (
                    call_info["model_param"]
                    or subagent_models.get(tool_use_id, "unknown")
                )
                data.subagent_calls.append(SubagentCall(
                    subagent_type=call_info["subagent_type"],
                    description=call_info["description"],
                    model=model,
                    usage=TokenUsage(
                        input_tokens=usage_raw.get("input_tokens", 0),
                        output_tokens=usage_raw.get("output_tokens", 0),
                        cache_write_tokens=usage_raw.get("cache_creation_input_tokens", 0),
                        cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
                    ),
                    duration_ms=result.get("totalDurationMs", 0),
                    tool_use_count=result.get("totalToolUseCount", 0),
                ))

    return data


def calculate_cost(usage: TokenUsage, model: str) -> float:
    """Calculate estimated API cost for a token usage at given model's pricing."""
    prices = PRICING.get(model, PRICING[FALLBACK_MODEL])
    return (
        (usage.input_tokens / 1_000_000) * prices["input"]
        + (usage.output_tokens / 1_000_000) * prices["output"]
        + (usage.cache_write_tokens / 1_000_000) * prices["cache_write"]
        + (usage.cache_read_tokens / 1_000_000) * prices["cache_read"]
    )
