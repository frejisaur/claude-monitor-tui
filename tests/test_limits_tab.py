"""Integration tests for the complete Limits feature with visual validation."""

import json
import os
from datetime import datetime, timezone, timedelta

import pytest

from claude_spend.data import (
    DashboardData, SessionSummary, TokenUsage,
    aggregate_by_day, aggregate_by_project, aggregate_by_model,
    aggregate_by_subagent_type, aggregate_by_skill, calculate_cost,
)
from claude_spend.quota import QuotaState, DataSource, build_quota_state
from claude_spend.plan_config import PLAN_BUDGETS, PlanBudget
from claude_spend.hook import UsageEntry
from claude_spend.usage_api import QuotaSnapshot


def _make_sessions_across_windows():
    """Build sessions spanning multiple time windows for realistic testing."""
    now = datetime.now(timezone.utc)
    sessions = []
    for i in range(3):
        usage = TokenUsage(input_tokens=10000, output_tokens=2000,
                           cache_write_tokens=500, cache_read_tokens=15000)
        model = "claude-opus-4-6"
        sessions.append(SessionSummary(
            session_id=f"today-{i}", project_name=["alpha", "beta", "alpha"][i],
            start_time=now - timedelta(hours=i + 1),
            duration_minutes=30, estimated_cost=calculate_cost(usage, model),
            usage_by_model={model: usage}, turn_count=10,
        ))
    for i in range(2):
        usage = TokenUsage(input_tokens=8000, output_tokens=1500,
                           cache_write_tokens=300, cache_read_tokens=12000)
        model = "claude-sonnet-4-6"
        sessions.append(SessionSummary(
            session_id=f"yesterday-{i}", project_name="beta",
            start_time=now - timedelta(days=1, hours=i),
            duration_minutes=45, estimated_cost=calculate_cost(usage, model),
            usage_by_model={model: usage}, turn_count=15,
        ))
    return sessions


def _make_data(sessions):
    return DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type([]),
        all_subagent_calls=[],
        skill_types=aggregate_by_skill(sessions, 0.0),
        baseline_avg_cost=0.0,
        total_cost=sum(s.estimated_cost for s in sessions),
        total_tokens=sum(s.total_usage.total for s in sessions),
    )


@pytest.mark.asyncio
async def test_full_limits_oauth_mode(tmp_path):
    """Full integration: OAuth data -> Overview gauges + Limits tab + session detail."""
    from claude_spend.dashboard import SpendApp, QuotaGauge, QuotaCard
    from textual.widgets import DataTable, Static

    sessions = _make_sessions_across_windows()
    data = _make_data(sessions)
    snap = QuotaSnapshot(
        session_pct=0.65, weekly_pct=0.35, weekly_sonnet_pct=0.12,
        session_reset_at=datetime.now(timezone.utc) + timedelta(hours=2, minutes=14),
        weekly_reset_at=datetime.now(timezone.utc) + timedelta(days=4, hours=6),
        weekly_sonnet_reset_at=None,
    )
    quota = build_quota_state(snap, [], PLAN_BUDGETS["max5"])
    app = SpendApp(data, "Last 7 days", quota_state=quota)

    async with app.run_test(size=(140, 50)) as pilot:
        gauges = app.query("QuotaGauge")
        assert len(gauges) >= 2

        tabs = app.query("Tab")
        for tab in tabs:
            if "Limits" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()

        cards = app.query("QuotaCard")
        assert len(cards) >= 2
        limits_table = app.query_one("#limits-sessions-table", DataTable)
        assert limits_table.row_count >= 1

        app.save_screenshot(str(tmp_path / "limits_oauth.svg"))
        assert os.path.isfile(str(tmp_path / "limits_oauth.svg"))


@pytest.mark.asyncio
async def test_full_limits_hook_only_mode(tmp_path):
    """Full integration: hook-only data -> Overview gauges from cost estimates."""
    from claude_spend.dashboard import SpendApp, QuotaGauge

    sessions = _make_sessions_across_windows()
    data = _make_data(sessions)

    now = datetime.now(timezone.utc)
    hook_entries = [
        UsageEntry(ts=now - timedelta(hours=1), session_id="today-0", message_id="m1",
                   model="claude-opus-4-6", input_tokens=10000, output_tokens=2000,
                   cache_write_tokens=500, cache_read_tokens=15000,
                   estimated_cost=1.50, project="alpha"),
        UsageEntry(ts=now - timedelta(hours=2), session_id="today-1", message_id="m2",
                   model="claude-opus-4-6", input_tokens=10000, output_tokens=2000,
                   cache_write_tokens=500, cache_read_tokens=15000,
                   estimated_cost=1.50, project="beta"),
    ]
    quota = build_quota_state(None, hook_entries, PLAN_BUDGETS["max5"])
    app = SpendApp(data, "Last 7 days", quota_state=quota)

    async with app.run_test(size=(140, 50)) as pilot:
        gauges = app.query("QuotaGauge")
        assert len(gauges) >= 2
        app.save_screenshot(str(tmp_path / "limits_hook.svg"))


@pytest.mark.asyncio
async def test_full_limits_no_data_mode(tmp_path):
    """Full integration: no quota data -> Limits tab shows install-hook prompt."""
    from claude_spend.dashboard import SpendApp

    sessions = _make_sessions_across_windows()
    data = _make_data(sessions)
    app = SpendApp(data, "Last 7 days", quota_state=None)

    async with app.run_test(size=(140, 50)) as pilot:
        tabs = app.query("Tab")
        for tab in tabs:
            if "Limits" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()

        no_data = app.query_one("#no-limits-data")
        content = str(no_data.render())
        assert "install-hook" in content
        app.save_screenshot(str(tmp_path / "limits_no_data.svg"))


@pytest.mark.asyncio
async def test_session_detail_plan_usage_integration(tmp_path):
    """Full integration: session detail shows PLAN USAGE section when quota present."""
    from claude_spend.dashboard import SpendApp
    from textual.widgets import DataTable, Static

    sessions = _make_sessions_across_windows()
    data = _make_data(sessions)
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.50, weekly_pct=0.30,
        estimated_5h_cost=4.40, estimated_weekly_cost=30.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)

    async with app.run_test(size=(140, 50)) as pilot:
        tabs = app.query("Tab")
        for tab in tabs:
            if "Sessions" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()

        sessions_table = app.query_one("#sessions-table", DataTable)
        sessions_table.move_cursor(row=0)
        sessions_table.action_select_cursor()
        await pilot.pause()

        detail = app.query_one("#session-detail", Static)
        content = str(detail.render())
        assert "PLAN USAGE" in content
        assert "5h:" in content
        assert "7d:" in content

        app.save_screenshot(str(tmp_path / "session_detail_plan_usage.svg"))
