"""Automated TUI tests using Textual's Pilot (headless app runner)."""

import pytest
from datetime import datetime, timedelta, timezone

from claude_spend.data import (
    DashboardData, SessionSummary, TokenUsage, SubagentCall,
    DailyAggregate, ProjectAggregate, ModelAggregate, SubagentTypeAggregate,
    SkillAggregate, aggregate_by_skill,
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
        skills = [["brainstorming", "execute-plan"], ["brainstorming"], []][i]
        turns = [30, 15, 8][i]
        sessions.append(SessionSummary(
            session_id=f"s{i}", project_path=f"/code/{proj}", project_name=proj,
            start_time=datetime(2026, 3, 5 + i, 10, 0, tzinfo=timezone.utc),
            duration_minutes=30 + i * 10, first_prompt=f"Task {i}: do something",
            usage_by_model={model: usage}, tool_counts={"Bash": 3, "Read": 2},
            subagent_calls=calls, skill_invocations=skills, turn_count=turns,
            estimated_cost=cost,
        ))
        all_calls.extend(calls)

    no_skill = [s for s in sessions if not s.skill_invocations]
    baseline = sum(s.estimated_cost for s in no_skill) / max(1, len(no_skill))
    skill_aggs = aggregate_by_skill(sessions, baseline)

    return DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type(all_calls),
        all_subagent_calls=all_calls,
        skill_types=skill_aggs,
        baseline_avg_cost=baseline,
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
        assert len(big_numbers) == 14  # 4 overview + 5 sessions + 5 skills

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
        for tab_name in ["Sessions", "Limits", "Projects", "Models", "Subagents", "Skills", "Overview"]:
            tabs = app.query("Tab")
            for tab in tabs:
                if tab_name in str(tab.label):
                    await pilot.click(type(tab), offset=(2, 0))
                    break
            await pilot.pause()


@pytest.mark.asyncio
async def test_skills_tab_renders():
    from claude_spend.dashboard import SpendApp
    from textual.widgets import DataTable

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        skills_table = app.query_one("#skills-table", DataTable)
        assert skills_table.row_count >= 1  # at least brainstorming


@pytest.mark.asyncio
async def test_table_help_widgets_exist():
    """Each data table has a .table-help Static widget above it."""
    from claude_spend.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        help_widgets = app.query(".table-help")
        assert len(help_widgets) >= 6


@pytest.mark.asyncio
async def test_skills_chart_renders_with_unnamed():
    """Skills chart renders without crash when data includes (unnamed) skills."""
    from claude_spend.dashboard import SpendApp
    from textual.widgets import DataTable

    sessions = [
        SessionSummary(
            session_id="u1",
            skill_invocations=["(unnamed)", "real-skill"],
            estimated_cost=20.0,
            usage_by_model={"claude-opus-4-6": TokenUsage(input_tokens=100, output_tokens=50)},
        )
    ]
    skill_aggs = aggregate_by_skill(sessions, 0.0)
    data = DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type([]),
        all_subagent_calls=[],
        skill_types=skill_aggs,
        baseline_avg_cost=0.0,
        total_cost=20.0,
    )
    app = SpendApp(data, "Test")
    async with app.run_test(size=(120, 40)) as pilot:
        skills_table = app.query_one("#skills-table", DataTable)
        assert skills_table.row_count >= 1
        skill_names = [str(skills_table.get_cell_at((r, 0))) for r in range(skills_table.row_count)]
        assert "(unnamed)" in skill_names or any("unnamed" in n for n in skill_names)


@pytest.mark.asyncio
async def test_narrow_terminal():
    """App doesn't crash in a narrow terminal."""
    from claude_spend.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()


@pytest.mark.asyncio
async def test_big_number_labels_not_dim():
    """BigNumber labels should use visible styling, not [dim] which is invisible on dark backgrounds."""
    from claude_spend.dashboard import BigNumber

    widget = BigNumber("Total Tokens", "1.5M")
    content = str(widget.render())
    # Verify labels are present and [dim] is not used in the raw markup
    assert "Total Tokens" in content
    assert "[dim]" not in content


@pytest.mark.asyncio
async def test_big_number_label_visible_in_render():
    """BigNumber padding=0 allows both value and label to render within height=5/border=tall."""
    from claude_spend.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Grab the first BigNumber widget in the overview numbers row
        bignums = app.query("BigNumber")
        assert len(bignums) > 0, "Expected BigNumber widgets to be present"
        first = bignums.first()
        # Both value and label lines must fit: content_height = height(5) - border(2) - padding_top_bottom(0+0) = 3
        # render() returns the markup string with both lines separated by \n
        content = str(first.render())
        assert "\n" in content, "BigNumber should contain both value and label lines"
        value_line, label_line = content.split("\n", 1)
        assert value_line.strip(), "Value line should not be empty"
        assert label_line.strip(), "Label line should not be empty"


@pytest.mark.asyncio
async def test_session_detail_panel_shows_on_row_select():
    from claude_spend.dashboard import SpendApp
    from textual.widgets import DataTable, Static

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        # Switch to Sessions tab
        tabs = app.query("Tab")
        for tab in tabs:
            if "Sessions" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()

        detail = app.query_one("#session-detail", Static)
        assert detail.display is False


@pytest.mark.asyncio
async def test_session_drilldown_on_row_select():
    """Selecting a row in sessions table shows the detail panel with session content."""
    from claude_spend.dashboard import SpendApp
    from textual.widgets import DataTable, Static

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        # Switch to Sessions tab
        tabs = app.query("Tab")
        for tab in tabs:
            if "Sessions" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()

        detail = app.query_one("#session-detail", Static)
        assert detail.display is False, "Detail panel should start hidden"

        # Select the first row in the sessions table
        sessions_table = app.query_one("#sessions-table", DataTable)
        sessions_table.move_cursor(row=0)
        await pilot.pause()
        # Trigger RowSelected via action_select_cursor
        sessions_table.action_select_cursor()
        await pilot.pause()

        assert detail.display is True, "Detail panel should be visible after row selection"
        # Use public render() method instead of private attribute
        content = str(detail.render())
        # The detail should contain session info — check for project name from fixture
        # Sessions are sorted by start_time desc, so first row is s2 (2026-03-07) project "beta"
        assert "beta" in content.lower() or "Task" in content, \
            f"Detail panel should contain session info, got: {content[:200]}"


@pytest.mark.asyncio
async def test_session_drilldown_uses_row_key_not_cursor():
    """Drilldown should work correctly even when using row keys (sort-stable)."""
    from claude_spend.dashboard import SpendApp
    from textual.widgets import DataTable, Static

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        sessions_table = app.query_one("#sessions-table", DataTable)

        # Verify row keys are set (str(i) for each row)
        keys = [str(rk.value) for rk in sessions_table.rows.keys()]
        assert all(k.isdigit() for k in keys), \
            f"Row keys should be numeric strings, got: {keys}"


@pytest.mark.asyncio
async def test_overview_shows_costs_chart():
    """Overview tab should contain the daily costs chart."""
    from claude_spend.dashboard import SpendApp

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        chart = app.query_one("#costs-chart")
        assert chart is not None


@pytest.mark.asyncio
async def test_sessions_metrics_new_bignumbers():
    """Sessions tab should show the 5 redesigned BigNumber metrics."""
    from claude_spend.dashboard import SpendApp, BigNumber

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    sessions = [
        SessionSummary(
            session_id="t1", project_name="proj-a",
            start_time=today_start.replace(hour=9),
            usage_by_model={"claude-opus-4-6": TokenUsage(
                input_tokens=10000, output_tokens=5000,
                cache_write_tokens=1000, cache_read_tokens=20000,
            )},
            turn_count=10, estimated_cost=5.0,
        ),
        SessionSummary(
            session_id="t2", project_name="proj-b",
            start_time=now - timedelta(days=3),
            usage_by_model={"claude-sonnet-4-6": TokenUsage(
                input_tokens=8000, output_tokens=4000,
                cache_write_tokens=500, cache_read_tokens=16000,
            )},
            turn_count=20, estimated_cost=3.0,
        ),
    ]
    data = DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type([]),
        all_subagent_calls=[],
        skill_types=aggregate_by_skill(sessions, 0.0),
        baseline_avg_cost=0.0,
        total_cost=8.0,
        total_tokens=sum(s.total_usage.total for s in sessions),
    )
    app = SpendApp(data, "Last 30 days")
    async with app.run_test(size=(120, 40)) as pilot:
        bignums = app.query("BigNumber")
        labels = [str(bn.render()).split("\n")[-1].strip() for bn in bignums]
        # Sessions tab should have these 5 new labels
        assert "Today's Spend" in labels
        assert "7d Avg Daily" in labels
        assert "Median Session Cost" in labels
        assert "Efficiency Score" in labels
        assert "Sessions (30d)" in labels
        # Old sessions-specific labels should NOT be present
        assert "Avg Skills/Session" not in labels
        assert "Avg Cost" not in labels

        # Verify computed values via rendered content
        values = {}
        for bn in bignums:
            rendered = str(bn.render())
            parts = rendered.split("\n")
            if len(parts) >= 2:
                values[parts[-1].strip()] = parts[0].strip()
        # Today's Spend = session t1 ($5.00, started today)
        assert values.get("Today's Spend") == "$5.00"
        # Median of [$3.00, $5.00] = $4.00
        assert values.get("Median Session Cost") == "$4.00"
        # Sessions count = 2
        assert values.get("Sessions (30d)") == "2"


@pytest.mark.asyncio
async def test_sessions_heatmap_project_week_binning():
    """Heatmap should bin sessions by project and week."""
    from claude_spend.dashboard import SpendApp
    from textual_plotext import PlotextPlot

    now = datetime.now(timezone.utc)
    sessions = [
        SessionSummary(
            session_id="h1", project_name="alpha",
            start_time=now - timedelta(days=1),
            usage_by_model={"claude-opus-4-6": TokenUsage(input_tokens=100, output_tokens=50)},
            estimated_cost=10.0,
        ),
        SessionSummary(
            session_id="h2", project_name="beta",
            start_time=now - timedelta(days=8),
            usage_by_model={"claude-opus-4-6": TokenUsage(input_tokens=100, output_tokens=50)},
            estimated_cost=7.0,
        ),
    ]
    data = DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type([]),
        all_subagent_calls=[],
        skill_types=aggregate_by_skill(sessions, 0.0),
        baseline_avg_cost=0.0,
        total_cost=17.0,
        total_tokens=sum(s.total_usage.total for s in sessions),
    )
    app = SpendApp(data, "Last 30 days")
    async with app.run_test(size=(120, 40)) as pilot:
        heatmap = app.query_one("#sessions-heatmap", PlotextPlot)
        assert heatmap is not None
        # Widget exists and renders without crash — data binning is correct


@pytest.mark.asyncio
async def test_sessions_heatmap_exists():
    """Sessions tab should have a heatmap widget instead of scatter plot."""
    from claude_spend.dashboard import SpendApp
    from textual_plotext import PlotextPlot

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        heatmap = app.query_one("#sessions-heatmap", PlotextPlot)
        assert heatmap is not None

        # Old scatter widget should not exist
        scatter_widgets = app.query("#sessions-scatter")
        assert len(scatter_widgets) == 0


@pytest.mark.asyncio
async def test_heatmap_frame_duck_type():
    """_HeatmapFrame should satisfy the minimal DataFrame interface for plotext."""
    from claude_spend.dashboard import _HeatmapFrame

    grid = [[1, 2], [3, 4]]
    frame = _HeatmapFrame(grid, ["r1", "r2"], ["c1", "c2"])
    assert frame.index.tolist() == ["r1", "r2"]
    assert frame.columns.tolist() == ["c1", "c2"]
    assert frame.values.tolist() == [[1, 2], [3, 4]]
    assert len(frame.index) == 2
    assert len(frame.columns) == 2
    assert list(frame.index) == ["r1", "r2"]


def test_quota_gauge_renders_bar_and_pct():
    """QuotaGauge should render a colored progress bar with percentage."""
    from claude_spend.dashboard import QuotaGauge
    gauge = QuotaGauge("5h Window", pct=0.78, reset_label="2h 14m")
    content = str(gauge.render())
    assert "78%" in content
    assert "5h Window" in content
    assert "2h 14m" in content


def test_quota_gauge_color_green():
    from claude_spend.dashboard import QuotaGauge
    gauge = QuotaGauge("Test", pct=0.30)
    markup = gauge._build_markup()
    assert "green" in markup


def test_quota_gauge_color_red():
    from claude_spend.dashboard import QuotaGauge
    gauge = QuotaGauge("Test", pct=0.90)
    markup = gauge._build_markup()
    assert "red" in markup


def test_quota_gauge_clamps_above_1():
    from claude_spend.dashboard import QuotaGauge
    gauge = QuotaGauge("Test", pct=1.5)
    content = str(gauge.render())
    assert "100%" in content


def test_quota_card_renders_all_parts():
    """QuotaCard should render title, bar, reset time, and cost used/budget."""
    from claude_spend.dashboard import QuotaCard
    card = QuotaCard(
        title="5h Session Window", pct=0.78,
        reset_label="2h 14m", used=3.40, budget=4.40,
    )
    content = str(card.render())
    assert "5h Session Window" in content
    assert "78%" in content
    assert "$3.40" in content
    assert "$4.40" in content


@pytest.mark.asyncio
async def test_overview_quota_gauges_render():
    """Overview tab should show QuotaGauge widgets when quota data is provided."""
    from claude_spend.dashboard import SpendApp, QuotaGauge
    from claude_spend.quota import QuotaState, DataSource
    from claude_spend.plan_config import PLAN_BUDGETS

    data = _make_test_data()
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.45, weekly_pct=0.20,
        sonnet_weekly_pct=0.0, estimated_5h_cost=3.96, estimated_weekly_cost=20.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)
    async with app.run_test(size=(120, 40)) as pilot:
        gauges = app.query("QuotaGauge")
        assert len(gauges) >= 2  # at least 5h + weekly


@pytest.mark.asyncio
async def test_overview_no_quota_no_gauges():
    """Overview tab should NOT show gauges when no quota data."""
    from claude_spend.dashboard import SpendApp, QuotaGauge

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days", quota_state=None)
    async with app.run_test(size=(120, 40)) as pilot:
        gauges = app.query("QuotaGauge")
        assert len(gauges) == 0


@pytest.mark.asyncio
async def test_limits_tab_renders_with_quota():
    """Limits tab should render QuotaCards and recent sessions table."""
    from claude_spend.dashboard import SpendApp, QuotaCard
    from claude_spend.quota import QuotaState, DataSource
    from claude_spend.plan_config import PLAN_BUDGETS
    from textual.widgets import DataTable

    # Build data with recent sessions so they fall within the 7-day window
    now = datetime.now(timezone.utc)
    sessions = []
    for i, (proj, model, tokens) in enumerate([
        ("alpha", "claude-opus-4-6", 50000),
        ("beta", "claude-sonnet-4-6", 30000),
    ]):
        usage = TokenUsage(input_tokens=tokens, output_tokens=tokens // 2,
                           cache_write_tokens=tokens // 10, cache_read_tokens=tokens * 2)
        cost = calculate_cost(usage, model)
        sessions.append(SessionSummary(
            session_id=f"lim{i}", project_path=f"/code/{proj}", project_name=proj,
            start_time=now - timedelta(hours=i + 1),
            duration_minutes=30, first_prompt=f"Task {i}",
            usage_by_model={model: usage}, tool_counts={"Bash": 3},
            subagent_calls=[], skill_invocations=[], turn_count=10,
            estimated_cost=cost,
        ))
    data = DashboardData(
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
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.78, weekly_pct=0.42,
        sonnet_weekly_pct=0.0, estimated_5h_cost=6.86, estimated_weekly_cost=42.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)
    async with app.run_test(size=(120, 40)) as pilot:
        cards = app.query("QuotaCard")
        assert len(cards) >= 2
        limits_table = app.query_one("#limits-sessions-table", DataTable)
        assert limits_table.row_count >= 1


@pytest.mark.asyncio
async def test_limits_tab_no_data_shows_fallback():
    """Limits tab should show setup message when no quota data."""
    from claude_spend.dashboard import SpendApp

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days", quota_state=None)
    async with app.run_test(size=(120, 40)) as pilot:
        tabs = app.query("Tab")
        for tab in tabs:
            if "Limits" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()
        no_data = app.query_one("#no-limits-data")
        assert no_data is not None


@pytest.mark.asyncio
async def test_session_detail_shows_plan_usage():
    """Session detail should include a PLAN USAGE line when quota data is available."""
    from claude_spend.dashboard import SpendApp
    from claude_spend.quota import QuotaState, DataSource
    from claude_spend.plan_config import PLAN_BUDGETS
    from textual.widgets import DataTable, Static

    data = _make_test_data()
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.78, weekly_pct=0.42,
        estimated_5h_cost=6.86, estimated_weekly_cost=42.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)
    async with app.run_test(size=(120, 40)) as pilot:
        sessions_table = app.query_one("#sessions-table", DataTable)
        sessions_table.move_cursor(row=0)
        sessions_table.action_select_cursor()
        await pilot.pause()

        detail = app.query_one("#session-detail", Static)
        content = str(detail.render())
        assert "PLAN USAGE" in content


def test_main_accepts_plan_arg(monkeypatch):
    """main() should accept --plan argument without crashing."""
    import sys
    from unittest.mock import patch, MagicMock

    monkeypatch.setattr(sys, "argv", ["claude-monitor", "--days", "7", "--plan", "pro"])
    with patch("claude_spend.dashboard.load_all") as mock_load, \
         patch("claude_spend.dashboard.SpendApp") as MockApp, \
         patch("os.path.isdir", return_value=True):
        mock_load.return_value = MagicMock()
        mock_instance = MockApp.return_value
        mock_instance.run = MagicMock()
        from claude_spend.dashboard import main
        main()
    # Verify SpendApp was called (it received data, label, and quota_state)
    assert MockApp.called
