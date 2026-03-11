# Sessions Revamp & Skills Tab Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revamp the Sessions tab with cost forensics (scatter chart, detail panel, cache metrics) and add a new Skills tab with usage analytics, cost correlation, and optimization signals.

**Architecture:** Data layer additions in `data.py` (new fields on SessionSummary, new SkillAggregate dataclass, new aggregation function). UI changes in `dashboard.py` (Sessions tab: BigNumbers + scatter + enhanced table + detail panel; Skills tab: BigNumbers + horizontal bar chart + performance table with colored cells).

**Tech Stack:** Python 3.12, Textual >=0.47.0, textual-plotext >=0.2.0, plotext >=5.2.0, Rich (for styled table cells and detail panel content)

**Spec:** `docs/superpowers/specs/2026-03-11-sessions-skills-design.md`

---

## File Structure

| File | Action | Responsibility |
|-|-|-|
| `claude_spend/data.py` | Modify | Add `SkillAggregate`, `aggregate_by_skill()`, new `SessionSummary` fields, `ConversationData.turn_count`, `DashboardData` additions |
| `claude_spend/dashboard.py` | Modify | Sessions tab revamp, Skills tab, formatters, CSS, event handlers |
| `tests/conftest.py` | Modify | Add user message to `sample_jsonl_messages` for turn_count testing |
| `tests/test_data_models.py` | Modify | Tests for new SessionSummary fields, SkillAggregate, aggregate_by_skill |
| `tests/test_session_parser.py` | Modify | Test for turn_count extraction from JSONL |
| `tests/test_dashboard.py` | Modify | Tests for Sessions revamp, Skills tab, detail panel |

---

## Chunk 1: Data Layer — New Fields and Parsing

### Task 1: Add turn_count to ConversationData and parsing

**Files:**
- Modify: `claude_spend/data.py:128-134` (ConversationData)
- Modify: `claude_spend/data.py:155-233` (parse_conversation_jsonl)
- Modify: `tests/conftest.py:36-146` (sample_jsonl_messages)
- Test: `tests/test_session_parser.py`

- [ ] **Step 1: Write the failing test for turn_count**

Add to `tests/test_session_parser.py`:

```python
def test_parse_conversation_extracts_turn_count(tmp_path, sample_jsonl_messages):
    jsonl_path = tmp_path / "session.jsonl"
    _write_jsonl(jsonl_path, sample_jsonl_messages)

    data = parse_conversation_jsonl(str(jsonl_path))
    # sample_jsonl_messages has 1 user message with tool result + 1 plain user message
    assert data.turn_count == 1  # only plain user messages, not tool results
```

- [ ] **Step 2: Add a plain user message to conftest fixture**

Add to `sample_jsonl_messages` in `tests/conftest.py` (after the Skill assistant message):

```python
# Plain user message (not a tool result)
{
    "type": "user",
    "message": {
        "role": "user",
        "content": [{"type": "text", "text": "looks good, now fix the tests"}],
    },
},
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_session_parser.py::test_parse_conversation_extracts_turn_count -v`
Expected: FAIL — `ConversationData` has no `turn_count` attribute

- [ ] **Step 4: Add turn_count field to ConversationData**

In `claude_spend/data.py`, modify the `ConversationData` dataclass:

```python
@dataclass
class ConversationData:
    usage_by_model: dict[str, TokenUsage] = field(default_factory=dict)
    subagent_calls: list[SubagentCall] = field(default_factory=list)
    skill_invocations: list[str] = field(default_factory=list)
    turn_count: int = 0
    parse_errors: int = 0
```

- [ ] **Step 5: Count user turns in parse_conversation_jsonl**

In `parse_conversation_jsonl`, inside the `for msg in lines:` loop, add a branch for plain user messages. After the existing `elif msg_type == "user":` block (which handles tool results), we need to also count non-tool-result user messages. Restructure the user handling:

Restructure the existing `elif msg_type == "user":` block into two branches. The existing code starts with:

```python
elif msg_type == "user":
    result = msg.get("toolUseResult")
    if not isinstance(result, dict) or "totalTokens" not in result:
        continue
    # ... tool result handling ...
```

Replace it with:

```python
elif msg_type == "user":
    result = msg.get("toolUseResult")
    if not isinstance(result, dict) or "totalTokens" not in result:
        # Plain user message (not a tool result) — count as a turn
        user_msg = msg.get("message", {})
        if isinstance(user_msg, dict):
            content = user_msg.get("content", [])
            has_text = any(
                isinstance(b, dict) and b.get("type") == "text"
                for b in (content if isinstance(content, list) else [])
            )
            if has_text:
                data.turn_count += 1
        continue

    # Existing tool result handling (unchanged from here down)
    tool_use_id = None
    user_msg = msg.get("message", {})
    for block in user_msg.get("content", []) if isinstance(user_msg, dict) else []:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            tool_use_id = block.get("tool_use_id")
            break

    if tool_use_id and tool_use_id in task_calls:
        # ... rest unchanged ...
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_session_parser.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add claude_spend/data.py tests/conftest.py tests/test_session_parser.py
git commit -m "feat: extract turn_count from JSONL user messages"
```

### Task 2: Add cache ratio fields to SessionSummary

**Files:**
- Modify: `claude_spend/data.py:250-268` (SessionSummary)
- Test: `tests/test_data_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_data_models.py`:

```python
def test_session_summary_cache_hit_ratio():
    from claude_spend.data import SessionSummary, TokenUsage
    s = SessionSummary(
        usage_by_model={"claude-opus-4-6": TokenUsage(
            input_tokens=1000, output_tokens=500,
            cache_write_tokens=200, cache_read_tokens=800,
        )},
    )
    # cache_hit_ratio = cache_read / (cache_read + cache_write + input) = 800 / 2000 = 0.4
    assert abs(s.cache_hit_ratio - 0.4) < 0.01


def test_session_summary_cache_rw_ratio():
    from claude_spend.data import SessionSummary, TokenUsage
    s = SessionSummary(
        usage_by_model={"claude-opus-4-6": TokenUsage(
            input_tokens=1000, output_tokens=500,
            cache_write_tokens=200, cache_read_tokens=800,
        )},
    )
    # cache_rw_ratio = cache_read / max(1, cache_write) = 800 / 200 = 4.0
    assert abs(s.cache_rw_ratio - 4.0) < 0.01


def test_session_summary_cache_ratios_zero_tokens():
    from claude_spend.data import SessionSummary, TokenUsage
    s = SessionSummary(
        usage_by_model={"claude-opus-4-6": TokenUsage()},
    )
    assert s.cache_hit_ratio == 0.0
    assert s.cache_rw_ratio == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data_models.py::test_session_summary_cache_hit_ratio tests/test_data_models.py::test_session_summary_cache_rw_ratio tests/test_data_models.py::test_session_summary_cache_ratios_zero_tokens -v`
Expected: FAIL — no `cache_hit_ratio` attribute

- [ ] **Step 3: Add cache ratio properties to SessionSummary**

In `claude_spend/data.py`, add to the `SessionSummary` dataclass after `total_usage`:

```python
@property
def cache_hit_ratio(self) -> float:
    u = self.total_usage
    denom = u.cache_read_tokens + u.cache_write_tokens + u.input_tokens
    return u.cache_read_tokens / denom if denom > 0 else 0.0

@property
def cache_rw_ratio(self) -> float:
    u = self.total_usage
    return u.cache_read_tokens / max(1, u.cache_write_tokens) if u.cache_read_tokens > 0 else 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/data.py tests/test_data_models.py
git commit -m "feat: add cache_hit_ratio and cache_rw_ratio properties to SessionSummary"
```

### Task 3: Add turn_count field to SessionSummary and wire in load_all

**Files:**
- Modify: `claude_spend/data.py:250-268` (SessionSummary)
- Modify: `claude_spend/data.py:400-510` (load_all)

- [ ] **Step 1: Add turn_count to SessionSummary dataclass**

In `claude_spend/data.py`, add to `SessionSummary`:

```python
turn_count: int = 0
```

- [ ] **Step 2: Wire turn_count into load_all**

In `load_all()`, where `SessionSummary` is constructed from parsed JSONL (the `if jsonl_path:` branch around line 423), add `turn_count=conv.turn_count`:

```python
session = SessionSummary(
    ...
    skill_invocations=conv.skill_invocations,
    turn_count=conv.turn_count,
    estimated_cost=cost,
)
```

- [ ] **Step 3: Run all tests to verify nothing breaks**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add claude_spend/data.py
git commit -m "feat: wire turn_count from JSONL into SessionSummary"
```

### Task 4: Add SkillAggregate and aggregate_by_skill

**Files:**
- Modify: `claude_spend/data.py` (after SubagentTypeAggregate)
- Test: `tests/test_data_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_data_models.py`:

```python
def test_aggregate_by_skill_basic():
    from claude_spend.data import SessionSummary, TokenUsage, aggregate_by_skill
    sessions = [
        SessionSummary(
            session_id="s1",
            skill_invocations=["brainstorming", "execute-plan"],
            estimated_cost=60.0,
            usage_by_model={"claude-opus-4-6": TokenUsage(
                input_tokens=1000, output_tokens=500,
                cache_write_tokens=200, cache_read_tokens=800,
            )},
            duration_minutes=120,
            turn_count=30,
        ),
        SessionSummary(
            session_id="s2",
            skill_invocations=["brainstorming"],
            estimated_cost=40.0,
            usage_by_model={"claude-opus-4-6": TokenUsage(
                input_tokens=1000, output_tokens=500,
                cache_write_tokens=100, cache_read_tokens=900,
            )},
            duration_minutes=60,
            turn_count=15,
        ),
        SessionSummary(
            session_id="s3",
            skill_invocations=[],
            estimated_cost=25.0,
            usage_by_model={"claude-opus-4-6": TokenUsage(
                input_tokens=500, output_tokens=250,
                cache_write_tokens=50, cache_read_tokens=400,
            )},
            duration_minutes=30,
            turn_count=8,
        ),
    ]
    baseline = 25.0  # only s3 has no skills
    aggs = aggregate_by_skill(sessions, baseline)

    # brainstorming appears in s1 and s2
    brain = next(a for a in aggs if a.skill_name == "brainstorming")
    assert brain.invocation_count == 2
    assert abs(brain.avg_session_cost - 50.0) < 0.01  # (60+40)/2
    assert abs(brain.cost_delta - 25.0) < 0.01  # 50 - 25

    # execute-plan appears in s1 only
    ep = next(a for a in aggs if a.skill_name == "execute-plan")
    assert ep.invocation_count == 1
    assert abs(ep.avg_session_cost - 60.0) < 0.01

    # sorted by cost_delta descending
    assert aggs[0].cost_delta >= aggs[-1].cost_delta


def test_aggregate_by_skill_empty():
    from claude_spend.data import aggregate_by_skill
    aggs = aggregate_by_skill([], 0.0)
    assert aggs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data_models.py::test_aggregate_by_skill_basic tests/test_data_models.py::test_aggregate_by_skill_empty -v`
Expected: FAIL — `aggregate_by_skill` not found

- [ ] **Step 3: Implement SkillAggregate and aggregate_by_skill**

Add to `claude_spend/data.py` after `SubagentTypeAggregate`:

```python
@dataclass
class SkillAggregate:
    skill_name: str = ""
    invocation_count: int = 0
    session_ids: list[str] = field(default_factory=list)
    avg_session_cost: float = 0.0
    cost_delta: float = 0.0
    avg_cache_hit_ratio: float = 0.0
    avg_cache_rw_ratio: float = 0.0
    avg_duration_minutes: int = 0
    avg_turn_count: int = 0


def aggregate_by_skill(sessions: list[SessionSummary], baseline_avg_cost: float) -> list[SkillAggregate]:
    by_skill: dict[str, list[SessionSummary]] = {}
    for s in sessions:
        for skill in s.skill_invocations:
            if skill not in by_skill:
                by_skill[skill] = []
            by_skill[skill].append(s)

    results = []
    for skill_name, skill_sessions in by_skill.items():
        n = len(skill_sessions)
        avg_cost = sum(s.estimated_cost for s in skill_sessions) / n
        avg_chr = sum(s.cache_hit_ratio for s in skill_sessions) / n
        avg_crw = sum(s.cache_rw_ratio for s in skill_sessions) / n
        avg_dur = sum(s.duration_minutes for s in skill_sessions) // n
        avg_turns = sum(s.turn_count for s in skill_sessions) // n
        results.append(SkillAggregate(
            skill_name=skill_name,
            invocation_count=n,
            session_ids=[s.session_id for s in skill_sessions],
            avg_session_cost=avg_cost,
            cost_delta=avg_cost - baseline_avg_cost,
            avg_cache_hit_ratio=avg_chr,
            avg_cache_rw_ratio=avg_crw,
            avg_duration_minutes=avg_dur,
            avg_turn_count=avg_turns,
        ))

    return sorted(results, key=lambda a: a.cost_delta, reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/data.py tests/test_data_models.py
git commit -m "feat: add SkillAggregate and aggregate_by_skill"
```

### Task 5: Wire skill aggregation into DashboardData and load_all

**Files:**
- Modify: `claude_spend/data.py:373-384` (DashboardData)
- Modify: `claude_spend/data.py:400-510` (load_all)

- [ ] **Step 1: Add fields to DashboardData**

```python
@dataclass
class DashboardData:
    sessions: list[SessionSummary] = field(default_factory=list)
    daily: list[DailyAggregate] = field(default_factory=list)
    projects: list[ProjectAggregate] = field(default_factory=list)
    models: list[ModelAggregate] = field(default_factory=list)
    subagent_types: list[SubagentTypeAggregate] = field(default_factory=list)
    all_subagent_calls: list[SubagentCall] = field(default_factory=list)
    skill_types: list[SkillAggregate] = field(default_factory=list)
    total_cost: float = 0.0
    total_tokens: int = 0
    baseline_avg_cost: float = 0.0
    parse_errors: int = 0
```

- [ ] **Step 2: Compute baseline and skill aggregation in load_all**

Add after `total_tokens` computation (around line 458), before `subagent_aggs`:

```python
# Skill aggregation
no_skill_sessions = [s for s in sessions if not s.skill_invocations]
baseline_avg_cost = (
    sum(s.estimated_cost for s in no_skill_sessions) / len(no_skill_sessions)
    if no_skill_sessions else total_cost / max(1, len(sessions))
)
skill_aggs = aggregate_by_skill(sessions, baseline_avg_cost)
```

Then in the `return DashboardData(...)` call, add:

```python
skill_types=skill_aggs,
baseline_avg_cost=baseline_avg_cost,
```

- [ ] **Step 3: Run all tests**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add claude_spend/data.py
git commit -m "feat: wire SkillAggregate into DashboardData.load_all"
```

---

## Chunk 2: Sessions Tab Revamp

### Task 6: Add formatting helpers for cache and cost delta

**Files:**
- Modify: `claude_spend/dashboard.py` (top of file, after existing formatters)

- [ ] **Step 1: Add Rich Text import and formatting functions**

Add `from rich.text import Text` to imports. Add after `_NUMERIC_COLUMNS`:

```python
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
```

Add new entries to `_NUMERIC_COLUMNS` (note: `_parse_pct_str` and `_parse_int_str` already exist in dashboard.py):

```python
"Cache Hit": _parse_pct_str,
"Cache R:W": lambda s: float(str(s).split(":")[0]) if ":" in str(s) else 0.0,
"Avg Turns": _parse_int_str,
"Cache%": _parse_pct_str,
```

Note: Cost Delta parser is deferred to Task 10 (Chunk 4) where the proper `_parse_cost_delta_str` function is defined.

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add claude_spend/dashboard.py
git commit -m "feat: add cache/cost formatting helpers with color thresholds"
```

### Task 7: Revamp Sessions tab layout — BigNumbers and scatter chart

**Files:**
- Modify: `claude_spend/dashboard.py` (compose method, CSS, populate methods)

- [ ] **Step 1: Update CSS**

Add to the CSS string:

```css
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
```

- [ ] **Step 2: Update compose() — Sessions tab**

Replace the Sessions TabPane section in `compose()`:

```python
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
    yield PlotextPlot(id="sessions-scatter")
    yield DataTable(id="sessions-table")
    yield Static(id="session-detail")
```

- [ ] **Step 3: Add _populate_sessions_scatter method**

```python
def _populate_sessions_scatter(self) -> None:
    if not self.data.sessions:
        return
    plt = self.query_one("#sessions-scatter", PlotextPlot).plt
    plt.title("Cost vs Duration (color = cache efficiency)")
    plt.theme("dark")

    buckets = {"red": ([], []), "orange+": ([], []), "green": ([], [])}
    for s in self.data.sessions:
        dur = s.duration_minutes
        cost = s.estimated_cost
        r = s.cache_hit_ratio
        if r < 0.50:
            buckets["red"][0].append(dur)
            buckets["red"][1].append(cost)
        elif r < 0.75:
            buckets["orange+"][0].append(dur)
            buckets["orange+"][1].append(cost)
        else:
            buckets["green"][0].append(dur)
            buckets["green"][1].append(cost)

    labels = {"red": "Low cache (<50%)", "orange+": "Mid (50-75%)", "green": "High cache (>75%)"}
    for color, (xs, ys) in buckets.items():
        if xs:
            plt.scatter(xs, ys, color=color, label=labels[color], marker="dot")

    plt.xlabel("Duration (min)")
    plt.ylabel("Cost ($)")
    max_cost = max((s.estimated_cost for s in self.data.sessions), default=0)
    _set_yticks(plt, max_cost, fmt=_fmt_cost)
```

- [ ] **Step 4: Update _populate_sessions_table to add Skills and Cache% columns**

```python
def _populate_sessions_table(self) -> None:
    table = self.query_one("#sessions-table", DataTable)
    table.cursor_type = "row"
    table.add_columns("Date", "Project", "First Prompt", "Duration", "Tokens", "Cost", "Skills", "Cache%")
    self._sessions_ordered = sorted(self.data.sessions, key=lambda x: x.start_time, reverse=True)
    for s in self._sessions_ordered:
        table.add_row(
            s.start_time.strftime("%Y-%m-%d %H:%M"),
            s.project_name[:25],
            s.first_prompt[:40],
            _fmt_duration(s.duration_minutes),
            _fmt_tokens(s.total_usage.total),
            _fmt_cost(s.estimated_cost),
            str(len(s.skill_invocations)),
            _fmt_cache_pct(s.cache_hit_ratio),
        )
```

- [ ] **Step 5: Call new populate methods in on_mount**

Add `self._populate_sessions_scatter()` to the `on_mount` method, alongside the existing `_populate_sessions_table()` call.

- [ ] **Step 6: Run tests**

Run: `pytest -v`
Expected: FAIL — `test_app_mounts_with_data` will fail because BigNumber count changed from 3 to 8 (3 overview + 5 sessions)

- [ ] **Step 7: Fix test_app_mounts_with_data**

In `tests/test_dashboard.py`, update the BigNumber assertion:

```python
big_numbers = app.query("BigNumber")
assert len(big_numbers) == 8  # 3 overview + 5 sessions
```

- [ ] **Step 8: Run tests again**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: revamp Sessions tab with BigNumbers, scatter chart, and cache columns"
```

### Task 8: Add session detail panel

**Files:**
- Modify: `claude_spend/dashboard.py` (event handler, detail builder)

- [ ] **Step 1: Add the detail builder method**

```python
def _build_session_detail(self, session: "SessionSummary") -> str:
    """Build Rich markup string for the session detail panel."""
    from claude_spend.data import calculate_cost, PRICING, FALLBACK_MODEL
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
    bar = "[green]" + "█" * fill + "[/green]" + "[dim]░[/dim]" * (bar_width - fill)
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
```

- [ ] **Step 2: Add the event handler with toggle-off on re-select**

```python
def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
    if event.data_table.id != "sessions-table":
        return
    detail = self.query_one("#session-detail", Static)
    if not hasattr(self, "_sessions_ordered"):
        return
    idx = event.cursor_row
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
```

- [ ] **Step 3: Add escape binding to hide detail**

Add to `BINDINGS`:

```python
Binding("escape", "hide_detail", "Close Detail", show=False),
```

Add method:

```python
def action_hide_detail(self) -> None:
    try:
        detail = self.query_one("#session-detail", Static)
        detail.display = False
    except Exception:
        pass
```

- [ ] **Step 4: Write test for detail panel**

Add to `tests/test_dashboard.py`:

```python
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
```

- [ ] **Step 5: Run tests**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: add session detail panel with cost breakdown, cache, skills, tools, subagents"
```

---

## Chunk 3: Skills Tab

### Task 9: Add Skills tab to dashboard

**Files:**
- Modify: `claude_spend/dashboard.py` (compose, populate methods, imports)
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Update compose() — add Skills tab**

In the `TabbedContent` call, add "Skills":

```python
with TabbedContent("Overview", "Sessions", "Projects", "Models", "Subagents", "Skills"):
```

Add the TabPane after Subagents:

```python
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
```

- [ ] **Step 2: Add CSS for skills-numbers**

```css
#skills-numbers {
    height: auto;
    max-height: 7;
}
```

- [ ] **Step 3: Add _populate_skills_chart method**

```python
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
```

- [ ] **Step 4: Add _populate_skills_table method**

```python
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
```

- [ ] **Step 5: Call populate methods in on_mount**

Add to `on_mount`:

```python
self._populate_skills_chart()
self._populate_skills_table()
```

- [ ] **Step 6: Update test fixture to include skill data**

In `tests/test_dashboard.py`, update `_make_test_data` to add skill_invocations to sessions and include `skill_types` and `baseline_avg_cost` in DashboardData. Import `SkillAggregate` and `aggregate_by_skill`.

```python
from claude_spend.data import (
    DashboardData, SessionSummary, TokenUsage, SubagentCall,
    DailyAggregate, ProjectAggregate, ModelAggregate, SubagentTypeAggregate,
    SkillAggregate, aggregate_by_skill,
    calculate_cost,
    aggregate_by_day, aggregate_by_project, aggregate_by_model, aggregate_by_subagent_type,
)
```

In the session creation loop, add skills and turn_count to sessions:

```python
skills = [["brainstorming", "execute-plan"], ["brainstorming"], []][i]
turns = [30, 15, 8][i]
```

Then pass `skill_invocations=skills, turn_count=turns` to `SessionSummary(...)`.

After building sessions, compute:

```python
no_skill = [s for s in sessions if not s.skill_invocations]
baseline = sum(s.estimated_cost for s in no_skill) / max(1, len(no_skill))
skill_aggs = aggregate_by_skill(sessions, baseline)
```

And add to `DashboardData(...)`:

```python
skill_types=skill_aggs,
baseline_avg_cost=baseline,
```

- [ ] **Step 7: Write test for Skills tab**

Add to `tests/test_dashboard.py`:

```python
@pytest.mark.asyncio
async def test_skills_tab_renders():
    from claude_spend.dashboard import SpendApp
    from textual.widgets import DataTable

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        skills_table = app.query_one("#skills-table", DataTable)
        assert skills_table.row_count >= 1  # at least brainstorming
```

- [ ] **Step 8: Update BigNumber count assertion**

The current codebase has BigNumbers only in Overview (3). After Sessions revamp (Task 7) that becomes 8. Adding Skills tab adds 5 more = 13. No other tabs have BigNumbers.

```python
big_numbers = app.query("BigNumber")
assert len(big_numbers) == 13  # 3 overview + 5 sessions + 5 skills
```

- [ ] **Step 9: Run all tests**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: add Skills tab with invocation chart, performance table, and cost correlation"
```

---

## Chunk 4: Integration and Polish

### Task 10: Update _NUMERIC_COLUMNS for Cost Delta sorting

**Files:**
- Modify: `claude_spend/dashboard.py`

- [ ] **Step 1: Add Cost Delta parser to _NUMERIC_COLUMNS**

The Cost Delta column contains Rich Text objects, not plain strings. When sorting, the DataTable's sort key receives the cell value. For Rich Text objects, `str(val)` gives the text content. Add the parser:

```python
"Cost Delta": lambda s: float(str(s).replace("+", "").replace("$", "")) if str(s).replace("+", "").replace("-", "").replace("$", "").replace(".", "").isdigit() else 0.0,
```

Simplify — strip `+`, `$`, `-` and parse:

```python
def _parse_cost_delta_str(s: str) -> float:
    try:
        return float(str(s).replace("+", "").replace("$", ""))
    except ValueError:
        return 0.0
```

Add `"Cost Delta": _parse_cost_delta_str` to `_NUMERIC_COLUMNS`.

- [ ] **Step 2: Run all tests**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add claude_spend/dashboard.py
git commit -m "feat: add Cost Delta column sort parser"
```

### Task 11: Final integration test

**Files:**
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Add comprehensive tab switching test including Skills**

Update `test_tab_switching` to include "Skills":

```python
for tab_name in ["Sessions", "Projects", "Models", "Subagents", "Skills", "Overview"]:
```

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Manual smoke test**

Run: `python -m claude_spend.dashboard --days 30`
Verify:
- Sessions tab: BigNumbers row, scatter chart, table with Skills/Cache% columns, click row shows detail panel, Escape hides it
- Skills tab: BigNumbers, horizontal bar chart, performance table with colored Cost Delta/Cache Hit/Cache R:W cells

- [ ] **Step 4: Commit**

```bash
git add tests/test_dashboard.py
git commit -m "test: add Skills tab to integration tests"
```
