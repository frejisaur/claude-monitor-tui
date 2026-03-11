# Sessions Revamp & Skills Tab Design

## Overview

Revamp the Sessions tab with cost forensics and cache efficiency visibility. Add a new Skills tab for skill usage analytics, cost correlation, and optimization signal detection.

## Goals

1. **Cost forensics**: drill into any session to see where money went (per-model breakdown, cache efficiency, subagent costs, tool/skill usage)
2. **Pattern recognition**: scatter chart to visually spot cost/efficiency outliers at a glance
3. **Skill optimization signals**: identify well-optimized skills (high cache reuse, low cost overhead) vs poorly-optimized ones (high cost delta, low cache R:W ratio)
4. **Custom skill support**: detect all skills equally — marketplace, superpowers, and user-created (e.g. `prospect`)

## Data Layer Changes

### New fields on `SessionSummary`

```python
cache_hit_ratio: float   # cache_read / (cache_read + cache_write + input_tokens)
cache_rw_ratio: float    # cache_read / max(1, cache_write)
turn_count: int          # count of user messages from JSONL
```

Computed during `load_all()` from `total_usage` and JSONL parsing.

### New: `parse_conversation_jsonl` additions

Count `type == "user"` messages (excluding tool results) to derive `turn_count`.

### New dataclass: `SkillAggregate`

```python
@dataclass
class SkillAggregate:
    skill_name: str = ""
    invocation_count: int = 0
    session_ids: list[str] = field(default_factory=list)
    avg_session_cost: float = 0.0
    cost_delta: float = 0.0           # avg_session_cost - baseline_avg_cost
    avg_cache_hit_ratio: float = 0.0
    avg_cache_rw_ratio: float = 0.0
    avg_duration_minutes: int = 0
    avg_turn_count: int = 0
```

### New function: `aggregate_by_skill(sessions, baseline_avg_cost) -> list[SkillAggregate]`

- Group sessions by each skill they invoked (a session using 3 skills counts toward all 3)
- Compute averages across the grouped sessions
- `baseline_avg_cost` = avg cost of sessions with zero skill invocations
- `cost_delta` = skill avg cost - baseline
- Sort by cost_delta descending (most expensive overhead first)

### New fields on `DashboardData`

```python
skill_types: list[SkillAggregate] = field(default_factory=list)
baseline_avg_cost: float = 0.0
```

## Sessions Tab Revamp

### Layout (top to bottom)

1. **BigNumbers row** (`Horizontal` container, 5 widgets):
   - Sessions count
   - Total Cost
   - Avg Cost per session
   - Avg Cache Hit %
   - Avg Skills/Session

2. **Scatter chart** (`PlotextPlot`):
   - X axis: duration (minutes)
   - Y axis: cost ($)
   - Three `plt.scatter()` calls, one per cache ratio bucket:
     - Red: cache_hit_ratio < 0.50
     - Orange: 0.50 <= cache_hit_ratio < 0.75
     - Green: cache_hit_ratio >= 0.75
   - Labels: "Low cache (<50%)", "Mid cache (50-75%)", "High cache (>75%)"

3. **Enhanced DataTable** (existing + 2 new columns):
   - Existing: Date, Project, First Prompt, Duration, Tokens, Cost
   - New: Skills (int count of skill_invocations), Cache% (formatted cache_hit_ratio)

4. **Detail panel** (`Static` widget, hidden by default):
   - Shown on `on_data_table_row_selected` event
   - Hidden when pressing Escape or selecting a different row while panel is visible
   - Content built as Rich renderable via `Static.update()`

### Detail panel content

Three-section layout using Rich markup:

**Section 1 — Cost Breakdown**
- Rich Table (no box): Model, Input, Output, Cache Write, Cache Read, Total
- One row per model used in the session

**Section 2 — Cache Efficiency**
- Progress bar: `[green]████████████████████████[/green][dim]░░░░░░[/dim] 81%`
- Stats line: `Read: 28.4M  Write: 6.6M  Ratio: 4.3:1`

**Section 3 — Skills & Tools**
- Skills: styled text tags `[blue on dark_blue] skill-name [/]`
- Tools: top 5 from tool_counts as `ToolName: N calls`

**Section 4 — Subagents**
- List of subagent calls: type, description (truncated), tokens, cost, model

### New CSS

```css
#session-detail {
    display: none;
    max-height: 15;
    border: tall $primary;
    padding: 1;
    margin: 0 1;
}
```

### Event handling

- `on_data_table_row_selected`: look up session by row index, build Rich content, call `detail.update(content)`, set `detail.display = True`
- Store session list in same order as table rows for index mapping
- Escape key or re-selecting same row toggles detail off

## Skills Tab (new 6th tab)

### Layout (top to bottom)

1. **BigNumbers row** (`Horizontal`, 5 widgets):
   - Total Invocations (sum of all skill invocation counts)
   - Unique Skills (count of distinct skill names)
   - Avg Cost (w/ skill) — avg cost of sessions that used at least one skill
   - Avg Cost (no skill) — baseline_avg_cost
   - Avg Cache Hit (skill sessions)

2. **Horizontal bar chart** (`PlotextPlot`):
   - `plt.bar(names, counts, orientation='horizontal', color='orange')`
   - Top 10 skills by invocation count
   - Skill names on y-axis (handles long names naturally)

3. **Performance DataTable**:
   - Columns: Skill, Uses, Avg Cost, Cost Delta, Cache Hit, Cache R:W, Avg Dur, Avg Turns
   - Sorted by Cost Delta descending (highest overhead first)
   - Column headers clickable for re-sorting (reuse existing sort infrastructure)

### Numeric column parsers

Add to `_NUMERIC_COLUMNS`:
- "Cost Delta": parse `+$X.XX` / `-$X.XX` format
- "Cache Hit": parse percentage
- "Cache R:W": parse `X.X:1` format
- "Avg Turns": parse int

### Tab integration

- Add "Skills" to `TabbedContent` as 6th tab after "Subagents"
- Add `TabPane("Skills", id="tab-skills")` with PlotextPlot + DataTable
- Add `_populate_skills_chart()` and `_populate_skills_table()` methods

## Formatting

### Color thresholds for table cells

DataTable supports Rich Text objects as cell values. Apply color based on value:

- **Cost Delta**: green if negative, orange if +$0-15, red if > +$15
- **Cache Hit**: green >= 75%, orange 50-74%, red < 50%
- **Cache R:W**: green >= 4:1, orange 2-4:1, red < 2:1
- **Cache%** (sessions table): same thresholds as Cache Hit

### Formatting functions

```python
def _fmt_cost_delta(delta: float) -> Text:
    sign = "+" if delta >= 0 else ""
    color = "green" if delta < 0 else "orange" if delta < 15 else "red"
    return Text(f"{sign}${delta:.2f}", style=color)

def _fmt_cache_pct(ratio: float) -> Text:
    pct = ratio * 100
    color = "green" if pct >= 75 else "orange" if pct >= 50 else "red"
    return Text(f"{pct:.0f}%", style=color)

def _fmt_cache_rw(ratio: float) -> Text:
    color = "green" if ratio >= 4 else "orange" if ratio >= 2 else "red"
    return Text(f"{ratio:.1f}:1", style=color)
```

## Files Changed

- `claude_spend/data.py`: SkillAggregate, aggregate_by_skill(), new SessionSummary fields, turn_count parsing, DashboardData additions
- `claude_spend/dashboard.py`: Sessions tab revamp (BigNumbers, scatter, detail panel), Skills tab (chart + table), new formatters, new CSS, event handlers
- `tests/test_data_models.py`: tests for SkillAggregate, aggregate_by_skill, new SessionSummary fields
- `tests/test_dashboard.py`: tests for new tab rendering
