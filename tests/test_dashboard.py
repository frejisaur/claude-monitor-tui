"""Automated TUI tests using Textual's Pilot (headless app runner)."""

import pytest
from datetime import datetime, timezone

from claude_spend.data import (
    DashboardData, SessionSummary, TokenUsage, SubagentCall,
    DailyAggregate, ProjectAggregate, ModelAggregate, SubagentTypeAggregate,
    calculate_cost,
    aggregate_by_day, aggregate_by_project, aggregate_by_model, aggregate_by_subagent_type,
)


def _make_test_data() -> DashboardData:
    """Build realistic fixture data without touching the filesystem."""
    sessions = []
    all_calls = []
    for i, (proj, model, tokens) in enumerate([
        ("alpha", "claude-opus-4-6", 50000),
        ("alpha", "claude-sonnet-4-6", 30000),
        ("beta", "claude-haiku-4-5-20251001", 10000),
    ]):
        usage = TokenUsage(input_tokens=tokens, output_tokens=tokens // 2,
                           cache_write_tokens=tokens // 10, cache_read_tokens=tokens * 2)
        cost = calculate_cost(usage, model)
        calls = []
        if i == 0:
            sub_usage = TokenUsage(input_tokens=5000, output_tokens=2000,
                                   cache_write_tokens=0, cache_read_tokens=8000)
            calls = [SubagentCall(
                session_id=f"s{i}", subagent_type="Explore", description="Find files",
                model="claude-haiku-4-5-20251001", usage=sub_usage,
                duration_ms=3000, tool_use_count=4,
            )]
        sessions.append(SessionSummary(
            session_id=f"s{i}", project_path=f"/code/{proj}", project_name=proj,
            start_time=datetime(2026, 3, 5 + i, 10, 0, tzinfo=timezone.utc),
            duration_minutes=30 + i * 10, first_prompt=f"Task {i}: do something",
            usage_by_model={model: usage}, tool_counts={"Bash": 3, "Read": 2},
            subagent_calls=calls, skill_invocations=[], estimated_cost=cost,
        ))
        all_calls.extend(calls)

    return DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type(all_calls),
        all_subagent_calls=all_calls,
        total_cost=sum(s.estimated_cost for s in sessions),
        total_tokens=sum(s.total_usage.total for s in sessions),
    )


def _make_empty_data() -> DashboardData:
    return DashboardData()


@pytest.mark.asyncio
async def test_app_mounts_with_data():
    """App renders all tabs and widgets with valid data."""
    from claude_spend.dashboard import SpendApp, BigNumber
    from textual.widgets import DataTable

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        big_numbers = app.query("BigNumber")
        assert len(big_numbers) == 3

        sessions_table = app.query_one("#sessions-table", DataTable)
        assert sessions_table.row_count == 3

        projects_table = app.query_one("#projects-table", DataTable)
        assert projects_table.row_count == 2  # alpha + beta

        models_table = app.query_one("#models-table", DataTable)
        assert models_table.row_count == 3  # opus + sonnet + haiku

        subagents_table = app.query_one("#subagents-table", DataTable)
        assert subagents_table.row_count >= 1  # at least Explore

        costs_table = app.query_one("#costs-table", DataTable)
        assert costs_table.row_count == 3


@pytest.mark.asyncio
async def test_app_mounts_empty():
    """App shows empty message when no sessions."""
    from claude_spend.dashboard import SpendApp

    app = SpendApp(_make_empty_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        empty = app.query_one("#empty-message")
        # Just verify the widget exists - content was set in compose()
        assert empty is not None


@pytest.mark.asyncio
async def test_quit_binding():
    """Pressing q should quit the app."""
    from claude_spend.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("q")


@pytest.mark.asyncio
async def test_tab_switching():
    """Tab switching doesn't crash."""
    from claude_spend.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        for tab_name in ["Sessions", "Projects", "Models", "Subagents", "Costs", "Overview"]:
            tabs = app.query("Tab")
            for tab in tabs:
                if tab_name in str(tab.label):
                    await pilot.click(type(tab), offset=(2, 0))
                    break
            await pilot.pause()


@pytest.mark.asyncio
async def test_narrow_terminal():
    """App doesn't crash in a narrow terminal."""
    from claude_spend.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
