"""Claude Spend — Token usage analytics dashboard for Claude Code."""

from __future__ import annotations

import argparse
import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (
    Header, Footer, Static, Label, DataTable, TabbedContent, TabPane, Sparkline,
)
from textual_plotext import PlotextPlot

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


class BigNumber(Static):
    """A large metric display widget."""

    def __init__(self, label: str, value: str, **kwargs):
        super().__init__(f"[b]{value}[/b]\n[dim]{label}[/dim]", **kwargs)


class SpendApp(App):
    CSS = """
    BigNumber {
        text-align: center;
        padding: 1 2;
        width: 1fr;
        height: 5;
        border: tall $surface-lighten-2;
    }
    #overview-numbers {
        height: auto;
        max-height: 7;
    }
    #overview-sparkline {
        height: 5;
        margin: 1 2;
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
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

        with TabbedContent("Overview", "Sessions", "Projects", "Models", "Subagents", "Costs"):
            with TabPane("Overview", id="tab-overview"):
                with Horizontal(id="overview-numbers"):
                    yield BigNumber("Total Tokens", _fmt_tokens(self.data.total_tokens))
                    yield BigNumber("Est. API Cost", _fmt_cost(self.data.total_cost))
                    yield BigNumber("Sessions", str(len(self.data.sessions)))

                yield PlotextPlot(id="overview-chart")

            with TabPane("Sessions", id="tab-sessions"):
                yield DataTable(id="sessions-table")

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

        if self.data.parse_errors > 0:
            yield Static(f"[dim]{self.data.parse_errors} lines skipped (parse errors)[/dim]")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Claude Spend — {self.days_label}"
        if self.data.sessions:
            self._populate_sessions_table()
            self._populate_projects_table()
            self._populate_models_table()
            self._populate_subagents_table()
            self._populate_costs_table()
            self._populate_overview_chart()
            self._populate_models_chart()
            self._populate_subagents_chart()
            self._populate_costs_chart()

    def _populate_sessions_table(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Date", "Project", "First Prompt", "Duration", "Tokens", "Cost")
        for s in sorted(self.data.sessions, key=lambda x: x.start_time, reverse=True):
            table.add_row(
                s.start_time.strftime("%Y-%m-%d %H:%M"),
                s.project_name[:25],
                s.first_prompt[:40],
                _fmt_duration(s.duration_minutes),
                _fmt_tokens(s.total_usage.total),
                _fmt_cost(s.estimated_cost),
            )

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

        for i, model in enumerate(models):
            values = [
                d.usage_by_model.get(model, TokenUsage()).total
                for d in self.data.daily
            ]
            short_name = model.split("-")[1] if "-" in model else model
            plt.bar(dates, values, label=short_name, color=colors[i % len(colors)])

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
