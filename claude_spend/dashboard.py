"""Claude Spend — Token usage analytics dashboard for Claude Code."""

from __future__ import annotations

import argparse
import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (
    Header, Footer, Static, Label, DataTable, TabbedContent, TabPane,
)
from textual_plotext import PlotextPlot
from rich.text import Text

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
        height: 15;
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "hide_detail", "Close Detail", show=False),
    ]

    def __init__(self, data: DashboardData, days_label: str):
        super().__init__()
        self.data = data
        self.days_label = days_label

    def compose(self) -> ComposeResult:
        yield Header()

        if not self.data.sessions:
            yield Static(
                f"No sessions found for the selected time range ({self.days_label}).",
                id="empty-message",
            )
            yield Footer()
            return

        with TabbedContent("Overview", "Sessions", "Projects", "Models", "Subagents", "Costs", "Skills"):
            with TabPane("Overview", id="tab-overview"):
                with Horizontal(id="overview-numbers"):
                    yield BigNumber("Total Tokens", _fmt_tokens(self.data.total_tokens))
                    yield BigNumber("Est. API Cost", _fmt_cost(self.data.total_cost))
                    yield BigNumber("Sessions", str(len(self.data.sessions)))

                yield PlotextPlot(id="overview-chart")

            with TabPane("Sessions", id="tab-sessions"):
                with Horizontal(id="sessions-numbers"):
                    n = len(self.data.sessions)
                    avg_cost = self.data.total_cost / max(1, n)
                    avg_cache = sum(s.cache_hit_ratio for s in self.data.sessions) / max(1, n)
                    avg_skills = sum(len(s.skill_invocations) for s in self.data.sessions) / max(1, n)
                    yield BigNumber("Sessions", str(n))
                    yield BigNumber("Total Cost", _fmt_cost(self.data.total_cost))
                    yield BigNumber("Avg Cost", _fmt_cost(avg_cost))
                    yield BigNumber("Avg Cache Hit", f"{avg_cache * 100:.0f}%")
                    yield BigNumber("Avg Skills/Session", f"{avg_skills:.1f}")
                yield PlotextPlot(id="sessions-heatmap")
                yield DataTable(id="sessions-table")
                yield Static(id="session-detail")

            with TabPane("Projects", id="tab-projects"):
                yield DataTable(id="projects-table")

            with TabPane("Models", id="tab-models"):
                yield PlotextPlot(id="models-chart")
                yield DataTable(id="models-table")

            with TabPane("Subagents", id="tab-subagents"):
                yield PlotextPlot(id="subagents-chart")
                yield DataTable(id="subagents-table")

            with TabPane("Costs", id="tab-costs"):
                yield PlotextPlot(id="costs-chart")
                yield DataTable(id="costs-table")

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
                yield DataTable(id="skills-table")

        if self.data.parse_errors > 0:
            yield Static(f"[dim]{self.data.parse_errors} lines skipped (parse errors)[/dim]")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Claude Spend — {self.days_label}"
        if self.data.sessions:
            self._populate_sessions_table()
            self._populate_sessions_heatmap()
            self._populate_projects_table()
            self._populate_models_table()
            self._populate_subagents_table()
            self._populate_costs_table()
            self._populate_overview_chart()
            self._populate_models_chart()
            self._populate_subagents_chart()
            self._populate_costs_chart()
            self._populate_skills_chart()
            self._populate_skills_table()

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
        plt.title("Session Density: Duration \u00d7 Cost  (brighter = more sessions)")
        plt.theme("dark")

        dur_labels = ["0-15m", "15-30m", "30-60m", "1-2h", "2-5h", "5h+"]
        cost_labels = ["$0-5", "$5-15", "$15-30", "$30-60", "$60-100", "$100+"]
        dur_edges = [0, 15, 30, 60, 120, 300, float("inf")]
        cost_edges = [0, 5, 15, 30, 60, 100, float("inf")]

        grid = [[0] * len(dur_labels) for _ in range(len(cost_labels))]
        for s in self.data.sessions:
            dur = s.duration_minutes
            cost = s.estimated_cost
            col = next((i for i in range(len(dur_edges) - 1) if dur_edges[i] <= dur < dur_edges[i + 1]), len(dur_labels) - 1)
            row = next((i for i in range(len(cost_edges) - 1) if cost_edges[i] <= cost < cost_edges[i + 1]), len(cost_labels) - 1)
            grid[row][col] += 1

        frame = _HeatmapFrame(grid, cost_labels, dur_labels)
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

    def _populate_overview_chart(self) -> None:
        if not self.data.daily:
            return
        plt = self.query_one("#overview-chart", PlotextPlot).plt
        plt.title("Daily Token Usage")
        plt.theme("dark")

        dates = [d.date[5:] for d in self.data.daily]  # MM-DD
        models = sorted({m for d in self.data.daily for m in d.usage_by_model})
        colors = ["red", "blue", "green", "yellow", "cyan"]

        max_val = 0
        for i, model in enumerate(models):
            values = [
                d.usage_by_model.get(model, TokenUsage()).total
                for d in self.data.daily
            ]
            if all(v == 0 for v in values):
                continue
            max_val = max(max_val, max(values))
            short_name = model.split("-")[1] if "-" in model else model
            plt.bar(dates, values, label=short_name, color=colors[i % len(colors)])

        if max_val > 0:
            import math
            num_ticks = 5
            step = max_val / num_ticks
            magnitude = 10 ** math.floor(math.log10(step))
            step = math.ceil(step / magnitude) * magnitude
            ticks = [i * step for i in range(num_ticks + 1)]
            labels = [_fmt_tokens(int(t)) for t in ticks]
            plt.yticks(ticks, labels)
        plt.ylabel("Tokens")

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

    def _populate_costs_chart(self) -> None:
        if not self.data.daily:
            return
        plt = self.query_one("#costs-chart", PlotextPlot).plt
        plt.title("Daily Cost by Token Type")
        plt.theme("dark")

        dates = [d.date[5:] for d in self.data.daily]
        colors = ["red", "orange+", "yellow", "green"]
        labels = ["Input", "Output", "Cache Write", "Cache Read"]

        for i, (label, attr) in enumerate(zip(labels, ["input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens"])):
            values = []
            for d in self.data.daily:
                total = sum(getattr(u, attr) for u in d.usage_by_model.values())
                values.append(total)
            plt.bar(dates, values, label=label, color=colors[i])

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
