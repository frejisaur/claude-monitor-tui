import json
from scripts.data import (
    TokenUsage, SessionSummary, SubagentCall,
    aggregate_by_day, aggregate_by_project, aggregate_by_model, aggregate_by_subagent_type,
    DailyAggregate, ProjectAggregate, ModelAggregate, SubagentTypeAggregate,
    load_all, DashboardData,
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


def test_load_all_integrates_meta_and_jsonl(tmp_claude_dir, sample_session_meta, sample_jsonl_messages):
    # Write session meta
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # Write JSONL in the right project directory
    project_encoded = sample_session_meta["project_path"].replace("/", "-")
    project_dir = tmp_claude_dir / "projects" / project_encoded
    project_dir.mkdir(parents=True)
    jsonl_path = project_dir / "abc-123.jsonl"
    with open(jsonl_path, "w") as f:
        for msg in sample_jsonl_messages:
            f.write(json.dumps(msg) + "\n")

    data = load_all(str(tmp_claude_dir), days=None)

    assert len(data.sessions) == 1
    session = data.sessions[0]
    assert "claude-opus-4-6" in session.usage_by_model
    assert len(session.subagent_calls) == 1
    assert session.estimated_cost > 0
    assert len(data.daily) >= 1
    assert len(data.projects) >= 1
    assert len(data.models) >= 1
    assert len(data.subagent_types) >= 1


def test_load_all_missing_claude_dir():
    data = load_all("/nonexistent/path", days=30)
    assert len(data.sessions) == 0


def test_load_all_session_without_jsonl_uses_meta_fallback(tmp_claude_dir, sample_session_meta):
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # No JSONL file — should still produce a session from meta
    data = load_all(str(tmp_claude_dir), days=None)
    assert len(data.sessions) == 1
    session = data.sessions[0]
    # Fallback uses meta totals with "unknown" model
    assert session.total_usage.input_tokens == sample_session_meta["input_tokens"]
