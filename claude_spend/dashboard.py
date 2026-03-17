"""Claude Spend — Token usage analytics dashboard for Claude Code."""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (
    Header, Footer, Static, Label, DataTable, TabbedContent, TabPane,
)
from textual_plotext import PlotextPlot
from rich.text import Text

import math

from claude_spend.data import load_all, DashboardData, calculate_cost, TokenUsage, PRICING, FALLBACK_MODEL


def _fmt_tokens(n: int) -> str:
    """Format token count: 1234567 -> '1.23M', 12345 -> '12.3k'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _fmt_cost(c: float) -> str:
    """Format cost: $12.34."""
    return f"${c:.2f}"


def _set_yticks(plt, max_val: float, fmt=_fmt_tokens, num_ticks: int = 5) -> None:
    """Set nice y-axis ticks with human-readable labels."""
    if max_val <= 0:
        return
    step = max_val / num_ticks
    magnitude = 10 ** math.floor(math.log10(step))
    step = math.ceil(step / magnitude) * magnitude
    ticks = [i * step for i in range(num_ticks + 1)]
    labels = [fmt(int(t)) for t in ticks]
    plt.yticks(ticks, labels)


def _fmt_duration(mins: int) -> str:
    if mins >= 60:
        return f"{mins // 60}h {mins % 60}m"
    return f"{mins}m"


def _fmt_cache_pct(ratio: float) -> Text:
    pct = ratio * 100
    color = "green" if pct >= 75 else "dark_orange" if pct >= 50 else "red"
    return Text(f"{pct:.0f}%", style=color)


def _fmt_cache_rw(ratio: float) -> Text:
    color = "green" if ratio >= 4 else "dark_orange" if ratio >= 2 else "red"
    return Text(f"{ratio:.1f}:1", style=color)


def _fmt_cost_delta(delta: float) -> Text:
    color = "green" if delta < 0 else "dark_orange" if delta < 15 else "red"
    if delta >= 0:
        return Text(f"+${delta:.2f}", style=color)
    return Text(f"-${abs(delta):.2f}", style=color)


def _parse_tokens_str(s: str) -> float:
    """Parse formatted token string back to a number for sorting."""
    s = str(s).strip()
    if s.endswith("M"):
        return float(s[:-1]) * 1_000_000
    if s.endswith("k"):
        return float(s[:-1]) * 1_000
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_cost_str(s: str) -> float:
    """Parse formatted cost string back to a number for sorting."""
    try:
        return float(str(s).lstrip("$"))
    except ValueError:
        return 0.0


def _parse_duration_str(s: str) -> int:
    """Parse formatted duration string back to minutes for sorting."""
    total = 0
    s = str(s).strip()
    if "h" in s:
        parts = s.split("h")
        total += int(parts[0].strip()) * 60
        s = parts[1]
    if "m" in s:
        s = s.replace("m", "").strip()
        if s:
            total += int(s)
    return total


def _parse_pct_str(s: str) -> float:
    """Parse percentage string back to a number for sorting."""
    try:
        return float(str(s).rstrip("%"))
    except ValueError:
        return 0.0


def _parse_int_str(s: str) -> int:
    """Parse integer string for sorting."""
    try:
        return int(str(s).strip())
    except ValueError:
        return 0


_NUMERIC_COLUMNS: dict[str, callable] = {
    "Tokens": _parse_tokens_str,
    "Cost": _parse_cost_str,
    "Total": _parse_cost_str,
    "Duration": _parse_duration_str,
    "Sessions": _parse_int_str,
    "Calls": _parse_int_str,
    "Input": _parse_tokens_str,
    "Output": _parse_tokens_str,
    "Cache Write": _parse_tokens_str,
    "Cache Read": _parse_tokens_str,
    "Avg Tokens": _parse_tokens_str,
    "Total Tokens": _parse_tokens_str,
    "%": _parse_pct_str,
    "Input Cost": _parse_cost_str,
    "Output Cost": _parse_cost_str,
    "Cache Write Cost": _parse_cost_str,
    "Cache Read Cost": _parse_cost_str,
    "Cache Hit": _parse_pct_str,
    "Cache R:W": lambda s: float(str(s).split(":")[0]) if ":" in str(s) else 0.0,
    "Avg Turns": _parse_int_str,
    "Cost Delta": lambda s: float(str(s).replace("+", "").replace("$", "")) if str(s).strip() else 0.0,
}


class _HeatmapFrame:
    """Minimal DataFrame-like object for plotext.heatmap() (avoids pandas dependency)."""
    class _Labels:
        def __init__(self, labels):
            self._labels = labels
        def tolist(self):
            return self._labels
        def __len__(self):
            return len(self._labels)
        def __iter__(self):
            return iter(self._labels)

    class _Values:
        def __init__(self, grid):
            self._grid = grid
        def tolist(self):
            return self._grid

    def __init__(self, grid, row_labels, col_labels):
        self.index = self._Labels(row_labels)
        self.columns = self._Labels(col_labels)
        self.values = self._Values(grid)

    def __repr__(self):
        return ""


class BigNumber(Static):
    """A large metric display widget."""

    def __init__(self, label: str, value: str, **kwargs):
        super().__init__(f"[b]{value}[/b]\n[#888888]{label}[/#888888]", **kwargs)


class SpendApp(App):
    CSS = """
    BigNumber {
        text-align: center;
        padding: 0 2;
        width: 1fr;
        height: 5;
        border: tall $surface-lighten-2;
    }
    #overview-numbers {
        height: auto;
        max-height: 7;
    }
.tab-content {
        padding: 1;
    }
    #empty-message {
        text-align: center;
        margin: 10 0;
    }
    PlotextPlot {
        height: 1fr;
        min-height: 15;
        margin: 0 1;
    }
    #sessions-numbers {
        height: auto;
        max-height: 7;
    }
    #session-detail {
        display: none;
        max-height: 15;
        border: tall $primary;
        padding: 1;
        margin: 0 1;
    }
    #skills-numbers {
        height: auto;
        max-height: 7;
    }
    .table-help {
        height: auto;
        margin: 0 1;
        padding: 0 1;
    }
    #subagents-tables {
        height: 1fr;
    }
    #subagents-tables DataTable {
        width: 1fr;
    }
    #effectiveness-numbers {
        height: auto;
        max-height: 7;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "hide_detail", "Close Detail", show=False),
    ]

    def __init__(self, data: DashboardData, days_label: str):
        super().__init__()
        self.data = data
        self.days_label = days_label
        self._sort_state: dict[str, tuple[str, bool]] = {}

    def compose(self) -> ComposeResult:
        yield Header()

        if not self.data.sessions:
            yield Static(
                f"No sessions found for the selected time range ({self.days_label}).",
                id="empty-message",
            )
            yield Footer()
            return

        with TabbedContent("Overview", "Effectiveness", "Sessions", "Projects", "Models", "Subagents", "Skills"):
            with TabPane("Overview", id="tab-overview"):
                with Horizontal(id="overview-numbers"):
                    yield BigNumber("Total Tokens", _fmt_tokens(self.data.total_tokens))
                    yield BigNumber("Est. API Cost", _fmt_cost(self.data.total_cost))
                    yield BigNumber("Sessions", str(len(self.data.sessions)))

                yield PlotextPlot(id="costs-chart")
                yield Static("[#666666]Cost by token type per model[/#666666]", classes="table-help")
                yield DataTable(id="costs-table")

            with TabPane("Effectiveness", id="tab-effectiveness"):
                if self.data.effectiveness_agg and self.data.effectiveness:
                    agg = self.data.effectiveness_agg
                    with Horizontal(id="effectiveness-numbers"):
                        yield BigNumber("Analyzed", f"{agg.faceted_count}f / {agg.proxied_count}p / {agg.total_sessions}")
                        yield BigNumber("Achievement", f"{agg.achievement_rate * 100:.0f}%")
                        yield BigNumber("Avg Friction", f"{agg.avg_friction:.1f}/session")
                        eff_label = f"{agg.avg_efficiency:.2f}x" if agg.avg_efficiency > 0 else "n/a"
                        yield BigNumber("Avg Efficiency", eff_label)
                    yield Static("[#666666]Friction types ranked by frequency[/#666666]", classes="table-help")
                    yield DataTable(id="friction-table")
                    yield Static("[#666666]Efficiency = session cost / category avg cost[/#666666]", classes="table-help")
                    yield DataTable(id="category-table")
                else:
                    yield Static(
                        "[dim]No effectiveness data available. Run /insights to generate session facets.[/dim]",
                        id="no-effectiveness",
                    )

            with TabPane("Sessions", id="tab-sessions"):
                with Horizontal(id="sessions-numbers"):
                    now = datetime.now(timezone.utc)
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_spend = sum(
                        s.estimated_cost for s in self.data.sessions
                        if s.start_time >= today_start
                    )
                    seven_day_ago = now - timedelta(days=7)
                    seven_day_cost = sum(
                        s.estimated_cost for s in self.data.sessions
                        if s.start_time >= seven_day_ago
                    )
                    seven_day_avg = seven_day_cost / 7
                    costs = [s.estimated_cost for s in self.data.sessions]
                    median_cost = statistics.median(costs) if costs else 0.0
                    scored = []
                    for s in self.data.sessions:
                        if s.turn_count == 0:
                            continue
                        cpt = s.estimated_cost / max(1, s.turn_count)
                        score = (s.cache_hit_ratio * 50) + (1 - min(cpt, 5) / 5) * 50
                        scored.append(max(0, min(100, score)))
                    efficiency = sum(scored) / len(scored) if scored else 0.0
                    yield BigNumber("Today's Spend", _fmt_cost(today_spend))
                    yield BigNumber("7d Avg Daily", _fmt_cost(seven_day_avg))
                    yield BigNumber("Median Session Cost", _fmt_cost(median_cost))
                    yield BigNumber("Efficiency Score", f"{efficiency:.0f}")
                    yield BigNumber("Sessions (30d)", str(len(self.data.sessions)))
                yield PlotextPlot(id="sessions-heatmap")
                yield Static("[#666666]Cache% = cache read / total input[/#666666]", classes="table-help")
                yield DataTable(id="sessions-table")
                yield Static(id="session-detail")

            with TabPane("Projects", id="tab-projects"):
                yield Static("[#666666]Tokens = total across all models[/#666666]", classes="table-help")
                yield DataTable(id="projects-table")

            with TabPane("Models", id="tab-models"):
                yield PlotextPlot(id="models-chart")
                yield Static("[#666666]% = share of total cost[/#666666]", classes="table-help")
                yield DataTable(id="models-table")

            with TabPane("Subagents", id="tab-subagents"):
                yield PlotextPlot(id="subagents-chart")
                yield Static("[#666666]Avg Tokens = per call[/#666666]", classes="table-help")
                with Horizontal(id="subagents-tables"):
                    yield DataTable(id="subagents-table")
                    yield DataTable(id="subagents-desc-table")

            with TabPane("Skills", id="tab-skills"):
                with Horizontal(id="skills-numbers"):
                    skill_sessions = [s for s in self.data.sessions if s.skill_invocations]
                    total_invocations = sum(len(s.skill_invocations) for s in self.data.sessions)
                    unique_skills = len(set(sk for s in self.data.sessions for sk in s.skill_invocations))
                    avg_skill_cost = (
                        sum(s.estimated_cost for s in skill_sessions) / len(skill_sessions)
                        if skill_sessions else 0
                    )
                    avg_skill_cache = (
                        sum(s.cache_hit_ratio for s in skill_sessions) / len(skill_sessions)
                        if skill_sessions else 0
                    )
                    yield BigNumber("Total Invocations", str(total_invocations))
                    yield BigNumber("Unique Skills", str(unique_skills))
                    yield BigNumber("Avg Cost (w/ skill)", _fmt_cost(avg_skill_cost))
                    yield BigNumber("Avg Cost (no skill)", _fmt_cost(self.data.baseline_avg_cost))
                    yield BigNumber("Avg Cache Hit", f"{avg_skill_cache * 100:.0f}%")
                yield PlotextPlot(id="skills-chart")
                yield Static("[#666666]Cost Delta = vs no-skill avg · Cache R:W = read:write ratio[/#666666]", classes="table-help")
                yield DataTable(id="skills-table")

        if self.data.parse_errors > 0:
            yield Static(f"[dim]{self.data.parse_errors} lines skipped (parse errors)[/dim]")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Claude Spend — {self.days_label}"
        self._charts_populated: set[str] = set()
        if self.data.sessions:
            # Populate tables (render fine in hidden tabs)
            self._populate_sessions_table()
            self._populate_projects_table()
            self._populate_models_table()
            self._populate_subagents_table()
            self._populate_subagents_desc_table()
            self._populate_costs_table()
            self._populate_skills_table()
            self._populate_friction_table()
            self._populate_category_table()
            # Only populate overview chart immediately (visible on mount)
            self._populate_costs_chart()
            self._charts_populated.add("tab-overview")

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Populate charts on first tab activation so they render at correct size."""
        if not self.data.sessions:
            return
        pane_id = event.pane.id
        if pane_id in self._charts_populated:
            return
        self._charts_populated.add(pane_id)
        chart_populators = {
            "tab-sessions": self._populate_sessions_heatmap,
            "tab-models": self._populate_models_chart,
            "tab-subagents": self._populate_subagents_chart,
            "tab-skills": self._populate_skills_chart,
        }
        if pane_id in chart_populators:
            chart_populators[pane_id]()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Sort table by clicked column header, toggling direction on re-click."""
        table = event.data_table
        col_key = event.column_key
        col_label = str(table.columns[col_key].label)

        table_id = table.id or ""
        prev_col, prev_reverse = self._sort_state.get(table_id, (None, False))
        reverse = not prev_reverse if prev_col == str(col_key) else False
        self._sort_state[table_id] = (str(col_key), reverse)

        parser = _NUMERIC_COLUMNS.get(col_label)
        if parser:
            table.sort(col_key, key=lambda val: parser(val), reverse=reverse)
        else:
            table.sort(col_key, key=lambda val: str(val).lower(), reverse=reverse)

    def _populate_sessions_table(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Date", "Project", "First Prompt", "Duration", "Tokens", "Cost", "Skills", "Cache%")
        self._sessions_ordered = sorted(self.data.sessions, key=lambda x: x.start_time, reverse=True)
        for i, s in enumerate(self._sessions_ordered):
            table.add_row(
                s.start_time.strftime("%Y-%m-%d %H:%M"),
                s.project_name[:25],
                s.first_prompt[:40],
                _fmt_duration(s.duration_minutes),
                _fmt_tokens(s.total_usage.total),
                _fmt_cost(s.estimated_cost),
                str(len(s.skill_invocations)),
                _fmt_cache_pct(s.cache_hit_ratio),
                key=str(i),
            )

    def _populate_sessions_heatmap(self) -> None:
        if not self.data.sessions:
            return
        plt = self.query_one("#sessions-heatmap", PlotextPlot).plt
        plt.title("Project Activity: Weekly Spend (brighter = higher cost)")
        plt.theme("dark")

        # Determine week columns: ISO weeks in the 30-day window
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=30)
        # Find the Monday of the week containing window_start
        first_monday = window_start - timedelta(days=window_start.weekday())
        weeks: list[tuple[datetime, str]] = []
        monday = first_monday
        while monday <= now:
            label = monday.strftime("%b %d")
            weeks.append((monday, label))
            monday += timedelta(days=7)

        # Aggregate spend per project
        project_spend: dict[str, float] = {}
        project_week_spend: dict[str, dict[int, float]] = {}
        for s in self.data.sessions:
            proj = s.project_name
            project_spend[proj] = project_spend.get(proj, 0) + s.estimated_cost
            # Find which week column this session belongs to
            for wi in range(len(weeks) - 1, -1, -1):
                if s.start_time >= weeks[wi][0]:
                    project_week_spend.setdefault(proj, {})[wi] = (
                        project_week_spend.get(proj, {}).get(wi, 0) + s.estimated_cost
                    )
                    break

        # Top N projects by total spend (cap at 10)
        top_projects = sorted(project_spend, key=project_spend.get, reverse=True)[:10]
        if not top_projects or not weeks:
            return

        week_labels = [w[1] for w in weeks]
        grid = []
        for proj in top_projects:
            row = [project_week_spend.get(proj, {}).get(wi, 0.0) for wi in range(len(weeks))]
            grid.append(row)

        # plotext heatmap crashes on all-zero grids (division by zero)
        if not any(v > 0 for row in grid for v in row):
            return

        frame = _HeatmapFrame(grid, top_projects, week_labels)
        plt.heatmap(frame)

    def _populate_projects_table(self) -> None:
        table = self.query_one("#projects-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Project", "Sessions", "Tokens", "Cost")
        for p in self.data.projects:
            table.add_row(
                p.project_name[:30],
                str(p.session_count),
                _fmt_tokens(p.total_usage.total),
                _fmt_cost(p.estimated_cost),
            )

    def _populate_models_table(self) -> None:
        table = self.query_one("#models-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Model", "Input", "Output", "Cache Write", "Cache Read", "Cost", "%")
        total = self.data.total_cost or 1
        for m in self.data.models:
            pct = (m.estimated_cost / total) * 100
            table.add_row(
                m.model,
                _fmt_tokens(m.total_usage.input_tokens),
                _fmt_tokens(m.total_usage.output_tokens),
                _fmt_tokens(m.total_usage.cache_write_tokens),
                _fmt_tokens(m.total_usage.cache_read_tokens),
                _fmt_cost(m.estimated_cost),
                f"{pct:.1f}%",
            )

    def _populate_subagents_table(self) -> None:
        table = self.query_one("#subagents-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Type", "Calls", "Avg Tokens", "Total Tokens", "Primary Model", "Cost")
        for a in self.data.subagent_types:
            primary_model = max(a.models_used, key=a.models_used.get) if a.models_used else "unknown"
            table.add_row(
                a.subagent_type,
                str(a.call_count),
                _fmt_tokens(a.avg_tokens_per_call),
                _fmt_tokens(a.total_usage.total),
                primary_model.split("-")[1] if "-" in primary_model else primary_model,
                _fmt_cost(a.estimated_cost),
            )

    def _populate_subagents_desc_table(self) -> None:
        table = self.query_one("#subagents-desc-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Description", "Type", "Tokens", "Cost")
        for c in self.data.all_subagent_calls[:50]:
            table.add_row(
                c.description[:45],
                c.subagent_type,
                _fmt_tokens(c.usage.total),
                _fmt_cost(calculate_cost(c.usage, c.model)),
            )

    def _populate_models_chart(self) -> None:
        if not self.data.models:
            return
        plt = self.query_one("#models-chart", PlotextPlot).plt
        plt.title("Cost by Model")
        plt.theme("dark")

        names = [m.model.split("-")[1] if "-" in m.model else m.model for m in self.data.models]
        costs = [m.estimated_cost for m in self.data.models]
        plt.bar(names, costs, color="blue")

    def _populate_subagents_chart(self) -> None:
        if not self.data.subagent_types:
            return
        plt = self.query_one("#subagents-chart", PlotextPlot).plt
        plt.title("Token Usage by Subagent Type")
        plt.theme("dark")

        types = [a.subagent_type for a in self.data.subagent_types]
        tokens = [a.total_usage.total for a in self.data.subagent_types]
        plt.bar(types, tokens, color="green")
        _set_yticks(plt, max(tokens) if tokens else 0)

    def _populate_skills_chart(self) -> None:
        if not self.data.skill_types:
            return
        plt = self.query_one("#skills-chart", PlotextPlot).plt
        plt.title("Skill Invocations")
        plt.theme("dark")

        # Top 10 by invocation count, reversed for horizontal bar (top item last)
        top = sorted(self.data.skill_types, key=lambda a: a.invocation_count)[-10:]
        names = [a.skill_name for a in top]
        counts = [a.invocation_count for a in top]
        plt.bar(names, counts, orientation="horizontal", color="orange+")
        plt.xlabel("Invocations")

    def _populate_skills_table(self) -> None:
        if not self.data.skill_types:
            return
        table = self.query_one("#skills-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Skill", "Uses", "Avg Cost", "Cost Delta", "Cache Hit", "Cache R:W", "Avg Dur", "Avg Turns")
        for a in self.data.skill_types:
            table.add_row(
                a.skill_name,
                str(a.invocation_count),
                _fmt_cost(a.avg_session_cost),
                _fmt_cost_delta(a.cost_delta),
                _fmt_cache_pct(a.avg_cache_hit_ratio),
                _fmt_cache_rw(a.avg_cache_rw_ratio),
                _fmt_duration(a.avg_duration_minutes),
                str(a.avg_turn_count),
            )

    def _populate_friction_table(self) -> None:
        agg = self.data.effectiveness_agg
        if not agg or not agg.friction_totals:
            return
        table = self.query_one("#friction-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Friction Type", "Count", "% Sessions", "Avg Extra Cost")
        total_sessions = agg.total_sessions or 1
        for ftype, count in sorted(agg.friction_totals.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total_sessions) * 100
            avg_extra = agg.friction_avg_extra_cost.get(ftype, 0.0)
            cost_color = "red" if avg_extra > 2.0 else "dark_orange" if avg_extra > 0.5 else "green"
            table.add_row(
                ftype, str(count), f"{pct:.0f}%",
                Text(f"+{_fmt_cost(avg_extra)}", style=cost_color),
            )

    def _populate_category_table(self) -> None:
        agg = self.data.effectiveness_agg
        if not agg or not agg.category_stats:
            return
        table = self.query_one("#category-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Category", "Sessions", "Avg Cost", "Avg Duration", "Achievement Rate", "Efficiency")
        for cat, stats in sorted(agg.category_stats.items(), key=lambda x: x[1]["sessions"], reverse=True):
            ach_pct = stats["achievement_rate"] * 100
            ach_color = "green" if ach_pct >= 70 else "dark_orange" if ach_pct >= 50 else "red"
            eff = stats["avg_efficiency"]
            eff_color = "green" if eff <= 1.0 else "dark_orange" if eff <= 1.5 else "red"
            table.add_row(
                cat,
                str(stats["sessions"]),
                _fmt_cost(stats["avg_cost"]),
                _fmt_duration(stats["avg_duration"]),
                Text(f"{ach_pct:.0f}%", style=ach_color),
                Text(f"{eff:.2f}x", style=eff_color) if eff > 0 else Text("n/a", style="dim"),
            )

    def _populate_costs_chart(self) -> None:
        if not self.data.daily:
            return
        plt = self.query_one("#costs-chart", PlotextPlot).plt
        plt.title("Daily Cost by Token Type")
        plt.theme("dark")

        dates = [d.date[5:] for d in self.data.daily]
        colors = ["red", "orange+", "yellow", "green"]
        labels = ["Input", "Output", "Cache Write", "Cache Read"]
        price_keys = ["input", "output", "cache_write", "cache_read"]
        token_attrs = ["input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens"]

        Y = []
        for attr, pkey in zip(token_attrs, price_keys):
            series = []
            for d in self.data.daily:
                day_cost = 0.0
                for model, usage in d.usage_by_model.items():
                    prices = PRICING.get(model, PRICING[FALLBACK_MODEL])
                    day_cost += (getattr(usage, attr) / 1_000_000) * prices[pkey]
                series.append(day_cost)
            Y.append(series)

        plt.stacked_bar(dates, Y, color=colors, labels=labels)
        max_val = max(sum(y[i] for y in Y) for i in range(len(dates))) if dates else 0
        _set_yticks(plt, max_val, fmt=_fmt_cost)
        plt.ylabel("Cost ($)")

    def _populate_costs_table(self) -> None:
        table = self.query_one("#costs-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Model", "Input Cost", "Output Cost", "Cache Write Cost", "Cache Read Cost", "Total")
        for m in self.data.models:
            prices = PRICING.get(m.model, PRICING[FALLBACK_MODEL])
            ic = (m.total_usage.input_tokens / 1_000_000) * prices["input"]
            oc = (m.total_usage.output_tokens / 1_000_000) * prices["output"]
            cwc = (m.total_usage.cache_write_tokens / 1_000_000) * prices["cache_write"]
            crc = (m.total_usage.cache_read_tokens / 1_000_000) * prices["cache_read"]
            table.add_row(
                m.model,
                _fmt_cost(ic), _fmt_cost(oc), _fmt_cost(cwc), _fmt_cost(crc),
                _fmt_cost(m.estimated_cost),
            )

    def _build_session_detail(self, session) -> str:
        """Build Rich markup string for the session detail panel."""
        lines = []

        # Header
        lines.append(
            f"[bold dodger_blue]Session Detail[/bold dodger_blue]  "
            f"[dim]{session.start_time.strftime('%Y-%m-%d %H:%M')} · "
            f"{session.project_name} · {_fmt_duration(session.duration_minutes)} · "
            f"[bold]{_fmt_cost(session.estimated_cost)}[/bold][/dim]"
        )
        lines.append("")

        # Cost breakdown
        lines.append("[dim]COST BREAKDOWN[/dim]")
        for model, usage in session.usage_by_model.items():
            prices = PRICING.get(model, PRICING[FALLBACK_MODEL])
            ic = (usage.input_tokens / 1_000_000) * prices["input"]
            oc = (usage.output_tokens / 1_000_000) * prices["output"]
            cwc = (usage.cache_write_tokens / 1_000_000) * prices["cache_write"]
            crc = (usage.cache_read_tokens / 1_000_000) * prices["cache_read"]
            total = ic + oc + cwc + crc
            short_model = model.split("-")[1] if "-" in model else model
            lines.append(
                f"  {short_model:<8} In:{_fmt_cost(ic):>7}  Out:{_fmt_cost(oc):>7}  "
                f"CW:{_fmt_cost(cwc):>7}  CR:[green]{_fmt_cost(crc):>7}[/green]  "
                f"= [bold]{_fmt_cost(total)}[/bold]"
            )

        # Cache efficiency
        u = session.total_usage
        bar_width = 30
        fill = int(session.cache_hit_ratio * bar_width)
        bar = "[green]" + "\u2588" * fill + "[/green]" + "[dim]\u2591[/dim]" * (bar_width - fill)
        pct = session.cache_hit_ratio * 100
        color = "green" if pct >= 75 else "dark_orange" if pct >= 50 else "red"
        lines.append("")
        lines.append(f"[dim]CACHE[/dim]  {bar} [{color}]{pct:.0f}%[/{color}]  "
                     f"[dim]Read: {_fmt_tokens(u.cache_read_tokens)}  "
                     f"Write: {_fmt_tokens(u.cache_write_tokens)}  "
                     f"R:W: {session.cache_rw_ratio:.1f}:1[/dim]")

        # Skills
        if session.skill_invocations:
            lines.append("")
            tags = "  ".join(f"[blue on dark_blue] {s} [/blue on dark_blue]" for s in session.skill_invocations)
            lines.append(f"[dim]SKILLS[/dim]  {tags}")

        # Tools (top 5)
        if session.tool_counts:
            sorted_tools = sorted(session.tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            tools_str = "  ".join(f"{name}:{count}" for name, count in sorted_tools)
            lines.append(f"[dim]TOOLS[/dim]   {tools_str}")

        # Subagents
        if session.subagent_calls:
            lines.append("")
            lines.append(f"[dim]SUBAGENTS ({len(session.subagent_calls)})[/dim]")
            for c in session.subagent_calls[:5]:
                cost = calculate_cost(c.usage, c.model)
                short_model = c.model.split("-")[1] if "-" in c.model else c.model
                lines.append(
                    f"  {c.subagent_type:<10} {c.description[:35]:<35}  "
                    f"{_fmt_tokens(c.usage.total):>6} tok  {_fmt_cost(cost):>7}  [dim]{short_model}[/dim]"
                )

        return "\n".join(lines)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "sessions-table":
            return
        detail = self.query_one("#session-detail", Static)
        if not hasattr(self, "_sessions_ordered"):
            return
        try:
            idx = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        if idx < 0 or idx >= len(self._sessions_ordered):
            return

        # Toggle off if re-selecting the same row
        if detail.display and getattr(self, "_detail_row_idx", -1) == idx:
            detail.display = False
            self._detail_row_idx = -1
            return

        session = self._sessions_ordered[idx]
        content = self._build_session_detail(session)
        detail.update(content)
        detail.display = True
        self._detail_row_idx = idx
        detail.scroll_visible()

    def action_hide_detail(self) -> None:
        try:
            detail = self.query_one("#session-detail", Static)
            detail.display = False
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Claude Spend — Token usage dashboard")
    parser.add_argument("--days", default="30", help="Number of days to show, or 'all'")
    args = parser.parse_args()

    claude_dir = os.path.expanduser("~/.claude")
    if not os.path.isdir(claude_dir):
        print("Claude Code data directory not found at ~/.claude/")
        sys.exit(1)

    if args.days.lower() == "all":
        days = None
        days_label = "All Time"
    else:
        try:
            days = int(args.days)
            days_label = f"Last {days} days"
        except ValueError:
            print(f"Invalid --days value: {args.days}")
            sys.exit(1)

    data = load_all(claude_dir, days=days)
    app = SpendApp(data, days_label)
    app.run()


if __name__ == "__main__":
    main()
