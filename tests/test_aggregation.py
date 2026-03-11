import json
from scripts.data import (
    TokenUsage, SessionSummary, SubagentCall,
    aggregate_by_day, aggregate_by_project, aggregate_by_model, aggregate_by_subagent_type,
    DailyAggregate, ProjectAggregate, ModelAggregate, SubagentTypeAggregate,
)
from datetime import datetime, timezone


def _make_session(session_id, project, date_str, model="claude-opus-4-6", tokens=1000):
    usage = TokenUsage(input_tokens=tokens, output_tokens=tokens // 2, cache_write_tokens=0, cache_read_tokens=0)
    return SessionSummary(
        session_id=session_id,
        project_path=f"/Users/test/code/{project}",
        project_name=project,
        start_time=datetime.fromisoformat(f"{date_str}T10:00:00+00:00"),
        duration_minutes=30,
        first_prompt="test prompt",
        usage_by_model={model: usage},
        tool_counts={},
        subagent_calls=[],
        skill_invocations=[],
        estimated_cost=0.0,
    )


def test_aggregate_by_day():
    sessions = [
        _make_session("s1", "proj", "2026-03-05", tokens=1000),
        _make_session("s2", "proj", "2026-03-05", tokens=2000),
        _make_session("s3", "proj", "2026-03-06", tokens=500),
    ]
    daily = aggregate_by_day(sessions)
    assert len(daily) == 2
    assert daily[0].date == "2026-03-05"
    assert daily[0].session_count == 2
    assert daily[1].date == "2026-03-06"
    assert daily[1].session_count == 1


def test_aggregate_by_project():
    sessions = [
        _make_session("s1", "alpha", "2026-03-05"),
        _make_session("s2", "alpha", "2026-03-06"),
        _make_session("s3", "beta", "2026-03-05"),
    ]
    projects = aggregate_by_project(sessions)
    assert len(projects) == 2
    alpha = next(p for p in projects if p.project_name == "alpha")
    assert alpha.session_count == 2


def test_aggregate_by_model():
    s1 = _make_session("s1", "proj", "2026-03-05", model="claude-opus-4-6", tokens=1000)
    s2 = _make_session("s2", "proj", "2026-03-05", model="claude-haiku-4-5-20251001", tokens=500)
    models = aggregate_by_model([s1, s2])
    assert len(models) == 2
    opus = next(m for m in models if m.model == "claude-opus-4-6")
    assert opus.total_usage.input_tokens == 1000


def test_aggregate_by_subagent_type():
    call1 = SubagentCall(
        session_id="s1", subagent_type="Explore", description="Find X",
        model="claude-haiku-4-5-20251001",
        usage=TokenUsage(input_tokens=5000, output_tokens=1000, cache_write_tokens=0, cache_read_tokens=0),
        duration_ms=3000, tool_use_count=2,
    )
    call2 = SubagentCall(
        session_id="s1", subagent_type="Explore", description="Find Y",
        model="claude-haiku-4-5-20251001",
        usage=TokenUsage(input_tokens=3000, output_tokens=800, cache_write_tokens=0, cache_read_tokens=0),
        duration_ms=2000, tool_use_count=1,
    )
    call3 = SubagentCall(
        session_id="s1", subagent_type="Plan", description="Plan Z",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input_tokens=10000, output_tokens=5000, cache_write_tokens=0, cache_read_tokens=0),
        duration_ms=8000, tool_use_count=5,
    )
    aggs = aggregate_by_subagent_type([call1, call2, call3])
    assert len(aggs) == 2
    explore = next(a for a in aggs if a.subagent_type == "Explore")
    assert explore.call_count == 2
    assert explore.total_usage.input_tokens == 8000
