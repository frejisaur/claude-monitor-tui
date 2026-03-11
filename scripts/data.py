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


@dataclass
class SessionSummary:
    session_id: str = ""
    project_path: str = ""
    project_name: str = ""
    start_time: datetime = field(default_factory=lambda: datetime(1970, 1, 1))
    duration_minutes: int = 0
    first_prompt: str = ""
    usage_by_model: dict[str, TokenUsage] = field(default_factory=dict)
    tool_counts: dict[str, int] = field(default_factory=dict)
    subagent_calls: list[SubagentCall] = field(default_factory=list)
    skill_invocations: list[str] = field(default_factory=list)
    estimated_cost: float = 0.0

    @property
    def total_usage(self) -> TokenUsage:
        result = TokenUsage()
        for u in self.usage_by_model.values():
            result = result + u
        return result


@dataclass
class DailyAggregate:
    date: str = ""
    usage_by_model: dict[str, TokenUsage] = field(default_factory=dict)
    session_count: int = 0
    estimated_cost: float = 0.0


@dataclass
class ProjectAggregate:
    project_name: str = ""
    project_path: str = ""
    session_count: int = 0
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost: float = 0.0


@dataclass
class ModelAggregate:
    model: str = ""
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    session_count: int = 0
    estimated_cost: float = 0.0


@dataclass
class SubagentTypeAggregate:
    subagent_type: str = ""
    call_count: int = 0
    models_used: dict[str, int] = field(default_factory=dict)
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    avg_tokens_per_call: int = 0
    total_duration_ms: int = 0
    estimated_cost: float = 0.0


def aggregate_by_day(sessions: list[SessionSummary]) -> list[DailyAggregate]:
    by_day: dict[str, DailyAggregate] = {}
    for s in sessions:
        date_str = s.start_time.strftime("%Y-%m-%d")
        if date_str not in by_day:
            by_day[date_str] = DailyAggregate(date=date_str)
        agg = by_day[date_str]
        agg.session_count += 1
        for model, usage in s.usage_by_model.items():
            if model in agg.usage_by_model:
                agg.usage_by_model[model] = agg.usage_by_model[model] + usage
            else:
                agg.usage_by_model[model] = TokenUsage(
                    usage.input_tokens, usage.output_tokens,
                    usage.cache_write_tokens, usage.cache_read_tokens,
                )
        agg.estimated_cost += s.estimated_cost
    return sorted(by_day.values(), key=lambda d: d.date)


def aggregate_by_project(sessions: list[SessionSummary]) -> list[ProjectAggregate]:
    by_proj: dict[str, ProjectAggregate] = {}
    for s in sessions:
        key = s.project_name
        if key not in by_proj:
            by_proj[key] = ProjectAggregate(project_name=key, project_path=s.project_path)
        agg = by_proj[key]
        agg.session_count += 1
        agg.total_usage = agg.total_usage + s.total_usage
        agg.estimated_cost += s.estimated_cost
    return sorted(by_proj.values(), key=lambda p: p.estimated_cost, reverse=True)


def aggregate_by_model(sessions: list[SessionSummary]) -> list[ModelAggregate]:
    by_model: dict[str, ModelAggregate] = {}
    for s in sessions:
        for model, usage in s.usage_by_model.items():
            if model not in by_model:
                by_model[model] = ModelAggregate(model=model)
            agg = by_model[model]
            agg.total_usage = agg.total_usage + usage
            agg.session_count += 1
            agg.estimated_cost += calculate_cost(usage, model)
    return sorted(by_model.values(), key=lambda m: m.estimated_cost, reverse=True)


def aggregate_by_subagent_type(calls: list[SubagentCall]) -> list[SubagentTypeAggregate]:
    by_type: dict[str, SubagentTypeAggregate] = {}
    for c in calls:
        key = c.subagent_type
        if key not in by_type:
            by_type[key] = SubagentTypeAggregate(subagent_type=key)
        agg = by_type[key]
        agg.call_count += 1
        agg.total_usage = agg.total_usage + c.usage
        agg.total_duration_ms += c.duration_ms
        agg.models_used[c.model] = agg.models_used.get(c.model, 0) + 1
        agg.estimated_cost += calculate_cost(c.usage, c.model)

    for agg in by_type.values():
        if agg.call_count > 0:
            agg.avg_tokens_per_call = agg.total_usage.total // agg.call_count

    return sorted(by_type.values(), key=lambda a: a.estimated_cost, reverse=True)


@dataclass
class DashboardData:
    sessions: list[SessionSummary] = field(default_factory=list)
    daily: list[DailyAggregate] = field(default_factory=list)
    projects: list[ProjectAggregate] = field(default_factory=list)
    models: list[ModelAggregate] = field(default_factory=list)
    subagent_types: list[SubagentTypeAggregate] = field(default_factory=list)
    all_subagent_calls: list[SubagentCall] = field(default_factory=list)
    total_cost: float = 0.0
    total_tokens: int = 0
    parse_errors: int = 0


def _find_jsonl(claude_dir: str, meta: SessionMeta) -> str | None:
    """Find the conversation JSONL for a session across project directories."""
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return None

    project_encoded = meta.project_path.replace("/", "-")
    jsonl_path = os.path.join(projects_dir, project_encoded, f"{meta.session_id}.jsonl")
    if os.path.isfile(jsonl_path):
        return jsonl_path
    return None


def load_all(claude_dir: str, days: int | None = 30) -> DashboardData:
    """Load all data and produce aggregated dashboard data."""
    if not os.path.isdir(claude_dir):
        return DashboardData()

    metas = load_session_metas(claude_dir, days=days)
    sessions: list[SessionSummary] = []
    all_subagent_calls: list[SubagentCall] = []
    total_parse_errors = 0

    for meta in metas:
        jsonl_path = _find_jsonl(claude_dir, meta)

        if jsonl_path:
            conv = parse_conversation_jsonl(jsonl_path)
            total_parse_errors += conv.parse_errors

            cost = sum(calculate_cost(u, m) for m, u in conv.usage_by_model.items())

            for call in conv.subagent_calls:
                call.session_id = meta.session_id

            session = SessionSummary(
                session_id=meta.session_id,
                project_path=meta.project_path,
                project_name=meta.project_name,
                start_time=meta.start_time,
                duration_minutes=meta.duration_minutes,
                first_prompt=meta.first_prompt,
                usage_by_model=conv.usage_by_model,
                tool_counts=meta.tool_counts,
                subagent_calls=conv.subagent_calls,
                skill_invocations=conv.skill_invocations,
                estimated_cost=cost,
            )
        else:
            fallback_usage = TokenUsage(
                input_tokens=meta.input_tokens,
                output_tokens=meta.output_tokens,
            )
            cost = calculate_cost(fallback_usage, FALLBACK_MODEL)
            session = SessionSummary(
                session_id=meta.session_id,
                project_path=meta.project_path,
                project_name=meta.project_name,
                start_time=meta.start_time,
                duration_minutes=meta.duration_minutes,
                first_prompt=meta.first_prompt,
                usage_by_model={"unknown": fallback_usage},
                tool_counts=meta.tool_counts,
                estimated_cost=cost,
            )

        sessions.append(session)
        all_subagent_calls.extend(session.subagent_calls)

    total_cost = sum(s.estimated_cost for s in sessions)
    total_tokens = sum(s.total_usage.total for s in sessions)

    return DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type(all_subagent_calls),
        all_subagent_calls=sorted(all_subagent_calls, key=lambda c: c.usage.total, reverse=True),
        total_cost=total_cost,
        total_tokens=total_tokens,
        parse_errors=total_parse_errors,
    )
