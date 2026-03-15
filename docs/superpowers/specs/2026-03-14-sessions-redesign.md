# Sessions Tab Redesign

## Problem

The current Sessions tab has three issues:
1. **Heatmap is uninformative** — Duration x Cost density just shows a bright top-left corner (most sessions are cheap and short). Doesn't help answer any real questions.
2. **Metrics are generic** — Sessions count, Total Cost, Avg Cost, Cache Hit %, Skills/Session are aggregates that don't drive action.
3. **Drilldown is broken** — Click/Enter on a table row doesn't expand the session detail panel.

## Goals

1. **Track usage patterns over time** — see which projects are active when and where money goes week over week
2. **Audit specific sessions** — quickly find a session and drill into its cost breakdown
3. **Compare session efficiency** — understand cost-per-turn and cache effectiveness

## Design

### Metrics Row (5 BigNumbers)

Replace current metrics with actionable ones:

| Position | Metric | Computation |
|-|-|-|
| 1 | Today's Spend | Sum of `estimated_cost` for sessions starting today |
| 2 | 7d Avg Daily | Total cost over last 7 days / 7 |
| 3 | Median Session Cost | Median of all session `estimated_cost` values |
| 4 | Efficiency Score | Composite: `(cache_hit_ratio * 50) + (1 - min(cost_per_turn, 5) / 5) * 50`, clamped 0-100. Higher = better. |
| 5 | Sessions (30d) | Total session count (kept for context) |

**Efficiency Score details:**
- `cost_per_turn = session.estimated_cost / max(1, session.turn_count)` per session
- Sessions with `turn_count == 0` (no JSONL data) are excluded from the average
- Weights cache hit rate (50%) and cost-per-turn efficiency (50%)
- A session with 100% cache hits and $0/turn scores 100; 0% cache and $5+/turn scores 0
- Final score is the average across all included sessions

### Chart: Project x Week Heatmap

Replace the Duration x Cost heatmap with a Project x Week heatmap.

- **Rows**: Top N projects by total spend (N fits available height, likely 6-10)
- **Columns**: ISO weeks in the 30-day window (4-5 columns, labeled as "MMM DD" of each Monday)
- **Cell value**: Total spend for that project in that week
- **Brightness**: Proportional to spend (brighter = more expensive)
- **Title**: "Project Activity: Weekly Spend (brighter = higher cost)"
- **Implementation**: Same `_HeatmapFrame` / plotext approach as current heatmap, just different data binning

This visualization shows:
- Which projects are active vs dormant
- Where spending is concentrated vs distributed
- Week-over-week trends per project

### Table (unchanged columns)

Keep existing columns: Date, Project, First Prompt, Duration, Tokens, Cost, Skills, Cache%

Sorted by date descending (most recent first). Column sorting remains clickable.

### Drilldown: Detail Panel Below Table

Fix the broken drilldown. The detail panel is a `Static` widget positioned below the `DataTable` in the DOM (Textual doesn't support inserting widgets between table rows).

Behavior:
- **Enter** on a row: show detail panel below the table with that session's info
- **Enter** again on same row: collapse the detail panel
- **Enter** on different row while expanded: update panel with new session's info
- **Escape**: collapse any open detail panel

The detail panel content stays the same (already implemented in `_build_session_detail`):
- Cost breakdown by model (input/output/cache write/cache read)
- Cache efficiency bar with percentage
- Skills as styled tags
- Top 5 tools with call counts
- Top 5 subagent calls with details

**Implementation note:** The current `on_data_table_row_selected` handler and `_build_session_detail` method exist but the panel toggle logic appears broken. Debug and fix the event handling — the `Static` widget's `display` toggle and row-key lookup need investigation.

## Data Layer Changes

### New computed values needed

```python
# On DashboardData or computed at display time:
today_spend: float           # sum of costs for today's sessions
seven_day_avg_daily: float   # total cost over last 7 days / 7
median_session_cost: float   # median of all session costs
efficiency_score: float      # composite score 0-100

# For heatmap binning:
project_week_matrix: dict[str, dict[str, float]]  # project -> week_label -> total_cost
```

### No new data model changes

All required data (session costs, cache ratios, project names, timestamps) already exists on `SessionSummary` and `DashboardData`. The new metrics and heatmap binning are pure display-layer computations.

## Files Changed

- `claude_spend/dashboard.py`: New metrics computation, new heatmap data binning, drilldown fix
- `tests/test_dashboard.py`: Updated tests for new metrics and heatmap
- `tests/test_session_parser.py`: May need updates if drilldown fix changes event handling

## Out of Scope

- No changes to other tabs (Overview, Projects, Models, Subagents, Skills)
- No data model changes in `data.py`
- No new dependencies
