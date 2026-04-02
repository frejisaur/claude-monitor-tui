# Plan Usage Limits — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add plan usage limit tracking (Pro/Max/20x) to the TUI dashboard using an OAuth API + Stop hook for data, with gauges on Overview, a dedicated Limits tab, and session detail enrichment.

**Architecture:** Two data sources feed a unified `QuotaState` that the dashboard consumes. (1) An OAuth API client fetches real-time quota percentages from Anthropic's undocumented endpoint. (2) A Stop hook logs per-turn usage to `~/.claude-spend/usage-log.jsonl`, from which rolling-window estimates are computed against configurable plan budgets. The dashboard prefers OAuth data when available, falls back to hook estimates.

**Tech Stack:** Python 3.10+, Textual TUI framework, pytest, pytest-asyncio. No new dependencies needed (uses stdlib `urllib.request` for HTTP).

**Spec:** `docs/superpowers/specs/2026-04-01-plan-usage-limits-design.md`

**Visual validation:** Every UI task includes a TUI screenshot step (using `app.save_screenshot()` in Textual pilot tests) to validate layout and rendering. Screenshots saved to `tests/screenshots/`.

**Review fixes applied:** This plan incorporates fixes from adversarial review:
- CRITICAL: Fixed historical chart to compute actual 5h sliding window peaks (not daily sums)
- CRITICAL: Dedup uses tail-read of last 50 lines instead of loading entire log (O(1) vs O(n))
- CRITICAL: Hook entries clearly documented as per-turn (not per-session) data
- HIGH: `compute_rolling_window` accepts injectable `now` parameter for deterministic tests
- HIGH: File locking (`fcntl.flock`) on usage-log writes for concurrent session safety
- HIGH: Unified session contribution % calculation across Limits table and session detail
- HIGH: OAuth response schema validation with runtime warning on unexpected shape
- MEDIUM: `round()` instead of `int()` for percentage display
- MEDIUM: Hook `main()` logs errors to `~/.claude-spend/hook.log`
- MEDIUM: Added test for hook `main()` stdin parsing
- MEDIUM: `--plan` only writes config when value differs from current

---

## File Structure

```
claude_spend/
  plan_config.py      # Plan budget constants + ~/.claude-spend/config.json management
  usage_api.py        # OAuth API client + QuotaSnapshot dataclass + caching
  hook.py             # Stop hook script (stdin→parse→append) + rolling window calc
  hook_install.py     # install-hook / uninstall-hook CLI commands
  quota.py            # Unified QuotaState that merges OAuth + hook data
  dashboard.py        # Modified: QuotaGauge, QuotaCard widgets, Limits tab, Overview row

tests/
  test_plan_config.py
  test_usage_api.py
  test_hook.py
  test_hook_install.py
  test_quota.py
  test_limits_tab.py
  screenshots/        # Visual validation outputs (gitignored)
```

---

### Task 1: Plan Configuration Module

**Files:**
- Create: `claude_spend/plan_config.py`
- Create: `tests/test_plan_config.py`

- [ ] **Step 1: Write failing tests for plan budget constants and config loading**

```python
# tests/test_plan_config.py
"""Tests for plan budget constants and config file management."""

import json
import os
import pytest

from claude_spend.plan_config import (
    PLAN_BUDGETS, PlanBudget, load_plan_config, save_plan_config, get_active_budget,
)


class TestPlanBudgets:
    def test_pro_budget_has_required_fields(self):
        b = PLAN_BUDGETS["pro"]
        assert isinstance(b, PlanBudget)
        assert b.five_hour_budget > 0
        assert b.weekly_budget > 0
        assert b.monthly_price == 20

    def test_max5_budget_is_5x_pro(self):
        pro = PLAN_BUDGETS["pro"]
        max5 = PLAN_BUDGETS["max5"]
        assert max5.five_hour_budget == pytest.approx(pro.five_hour_budget * 2, rel=0.3)
        assert max5.weekly_budget == pytest.approx(pro.weekly_budget * 5, rel=0.1)
        assert max5.monthly_price == 100

    def test_max20_budget_is_20x_pro(self):
        pro = PLAN_BUDGETS["pro"]
        max20 = PLAN_BUDGETS["max20"]
        assert max20.five_hour_budget == pytest.approx(pro.five_hour_budget * 5, rel=0.3)
        assert max20.weekly_budget == pytest.approx(pro.weekly_budget * 10, rel=0.1)
        assert max20.monthly_price == 200

    def test_all_plans_present(self):
        assert set(PLAN_BUDGETS.keys()) == {"pro", "max5", "max20"}


class TestConfigFile:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        config = load_plan_config(str(tmp_path / "nonexistent"))
        assert config["plan"] == "max5"
        assert config["custom_budgets"] is None

    def test_save_and_load_roundtrip(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="pro")
        loaded = load_plan_config(config_dir)
        assert loaded["plan"] == "pro"
        assert loaded["custom_budgets"] is None

    def test_save_with_custom_budgets(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="custom", custom_budgets={"5h_budget": 10.0, "weekly_budget": 150.0})
        loaded = load_plan_config(config_dir)
        assert loaded["plan"] == "custom"
        assert loaded["custom_budgets"]["5h_budget"] == 10.0

    def test_get_active_budget_named_plan(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="pro")
        budget = get_active_budget(config_dir)
        assert budget == PLAN_BUDGETS["pro"]

    def test_get_active_budget_custom(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="custom", custom_budgets={"5h_budget": 10.0, "weekly_budget": 150.0})
        budget = get_active_budget(config_dir)
        assert budget.five_hour_budget == 10.0
        assert budget.weekly_budget == 150.0

    def test_get_active_budget_unknown_plan_falls_back(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "config.json"), "w") as f:
            json.dump({"plan": "nonexistent", "custom_budgets": None}, f)
        budget = get_active_budget(config_dir)
        assert budget == PLAN_BUDGETS["max5"]  # default fallback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_spend.plan_config'`

- [ ] **Step 3: Implement plan_config.py**

```python
# claude_spend/plan_config.py
"""Plan budget constants and ~/.claude-spend/config.json management."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanBudget:
    """Budget limits for a Claude subscription plan."""
    name: str
    five_hour_budget: float   # estimated $ per 5h window
    weekly_budget: float      # estimated $ per 7d window
    monthly_price: int        # subscription price in $/mo


PLAN_BUDGETS: dict[str, PlanBudget] = {
    "pro": PlanBudget(name="Pro", five_hour_budget=4.40, weekly_budget=20.0, monthly_price=20),
    "max5": PlanBudget(name="Max 5x", five_hour_budget=8.80, weekly_budget=100.0, monthly_price=100),
    "max20": PlanBudget(name="Max 20x", five_hour_budget=22.0, weekly_budget=200.0, monthly_price=200),
}

DEFAULT_PLAN = "max5"

_DEFAULT_CONFIG = {"plan": DEFAULT_PLAN, "custom_budgets": None}


def _config_path(config_dir: str) -> str:
    return os.path.join(config_dir, "config.json")


def load_plan_config(config_dir: str) -> dict:
    """Load config from config_dir/config.json. Returns defaults if missing."""
    path = _config_path(config_dir)
    if not os.path.isfile(path):
        return dict(_DEFAULT_CONFIG)
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "plan": data.get("plan", DEFAULT_PLAN),
            "custom_budgets": data.get("custom_budgets"),
        }
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_CONFIG)


def save_plan_config(
    config_dir: str,
    plan: str = DEFAULT_PLAN,
    custom_budgets: dict | None = None,
) -> None:
    """Write config to config_dir/config.json, creating directory if needed."""
    os.makedirs(config_dir, exist_ok=True)
    with open(_config_path(config_dir), "w") as f:
        json.dump({"plan": plan, "custom_budgets": custom_budgets}, f, indent=2)


def get_active_budget(config_dir: str) -> PlanBudget:
    """Return the active PlanBudget based on config. Falls back to DEFAULT_PLAN."""
    config = load_plan_config(config_dir)
    plan = config["plan"]

    if plan == "custom" and config["custom_budgets"]:
        cb = config["custom_budgets"]
        return PlanBudget(
            name="Custom",
            five_hour_budget=cb.get("5h_budget", PLAN_BUDGETS[DEFAULT_PLAN].five_hour_budget),
            weekly_budget=cb.get("weekly_budget", PLAN_BUDGETS[DEFAULT_PLAN].weekly_budget),
            monthly_price=0,
        )

    return PLAN_BUDGETS.get(plan, PLAN_BUDGETS[DEFAULT_PLAN])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_config.py -v`
Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/plan_config.py tests/test_plan_config.py
git commit -m "feat: add plan budget constants and config module"
```

---

### Task 2: Usage Log + Rolling Windows (Hook Data Layer)

**Files:**
- Create: `claude_spend/hook.py`
- Create: `tests/test_hook.py`

This task builds the data layer for the Stop hook: parsing JSONL to extract usage, appending to the log, deduplication, and rolling window computation. The actual hook entry point (stdin parsing) is also included.

- [ ] **Step 1: Write failing tests for usage log operations and rolling windows**

```python
# tests/test_hook.py
"""Tests for Stop hook: usage extraction, log append, dedup, rolling windows."""

import json
import os
from datetime import datetime, timezone, timedelta

import pytest

from claude_spend.hook import (
    extract_latest_usage, append_usage_entry, load_usage_log,
    compute_rolling_window, compute_session_contributions,
    UsageEntry,
)


@pytest.fixture
def sample_jsonl_path(tmp_path):
    """Create a sample session JSONL with known usage data."""
    path = tmp_path / "session.jsonl"
    messages = [
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_001",
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {
                    "input_tokens": 3000,
                    "output_tokens": 500,
                    "cache_creation_input_tokens": 1000,
                    "cache_read_input_tokens": 2000,
                },
            },
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_002",
                "content": [{"type": "text", "text": "Done"}],
                "usage": {
                    "input_tokens": 5000,
                    "output_tokens": 800,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 4000,
                },
            },
        },
    ]
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return str(path)


class TestExtractLatestUsage:
    def test_extracts_last_assistant_message(self, sample_jsonl_path):
        entry = extract_latest_usage(sample_jsonl_path, "sess-1")
        assert entry is not None
        assert entry.model == "claude-opus-4-6"
        assert entry.input_tokens == 5000
        assert entry.output_tokens == 800
        assert entry.cache_write_tokens == 500
        assert entry.cache_read_tokens == 4000
        assert entry.message_id == "msg_002"

    def test_returns_none_for_missing_file(self, tmp_path):
        result = extract_latest_usage(str(tmp_path / "nope.jsonl"), "s1")
        assert result is None

    def test_returns_none_for_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        result = extract_latest_usage(str(path), "s1")
        assert result is None

    def test_estimated_cost_is_positive(self, sample_jsonl_path):
        entry = extract_latest_usage(sample_jsonl_path, "sess-1")
        assert entry.estimated_cost > 0


class TestAppendAndDedup:
    def test_append_creates_file(self, tmp_path):
        log_path = str(tmp_path / "usage-log.jsonl")
        entry = UsageEntry(
            ts=datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc),
            session_id="s1", message_id="msg_001", model="claude-opus-4-6",
            input_tokens=1000, output_tokens=200, cache_write_tokens=100,
            cache_read_tokens=500, estimated_cost=0.15, project="test",
        )
        append_usage_entry(log_path, entry)
        log = load_usage_log(log_path)
        assert len(log) == 1
        assert log[0].session_id == "s1"

    def test_append_is_additive(self, tmp_path):
        log_path = str(tmp_path / "usage-log.jsonl")
        for i in range(3):
            entry = UsageEntry(
                ts=datetime(2026, 4, 1, 14, i, tzinfo=timezone.utc),
                session_id="s1", message_id=f"msg_{i}", model="claude-opus-4-6",
                input_tokens=1000, output_tokens=200, cache_write_tokens=0,
                cache_read_tokens=0, estimated_cost=0.10, project="test",
            )
            append_usage_entry(log_path, entry)
        log = load_usage_log(log_path)
        assert len(log) == 3

    def test_dedup_skips_same_session_message(self, tmp_path):
        log_path = str(tmp_path / "usage-log.jsonl")
        entry = UsageEntry(
            ts=datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc),
            session_id="s1", message_id="msg_001", model="claude-opus-4-6",
            input_tokens=1000, output_tokens=200, cache_write_tokens=0,
            cache_read_tokens=0, estimated_cost=0.10, project="test",
        )
        append_usage_entry(log_path, entry)
        append_usage_entry(log_path, entry)  # duplicate
        log = load_usage_log(log_path)
        assert len(log) == 1


class TestRollingWindows:
    def _make_entries(self, now):
        """Entries spanning 8 hours, $0.50 each, 8 total = $4.00."""
        entries = []
        for i in range(8):
            entries.append(UsageEntry(
                ts=now - timedelta(hours=i + 0.5),  # offset by 30min to avoid boundary
                session_id=f"s{i}", message_id=f"m{i}", model="claude-opus-4-6",
                input_tokens=1000, output_tokens=200, cache_write_tokens=0,
                cache_read_tokens=0, estimated_cost=0.50, project="test",
            ))
        return entries

    def test_5h_window_sums_only_recent(self):
        now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
        entries = self._make_entries(now)
        # Entries at 0.5h,1.5h,2.5h,3.5h,4.5h are within 5h (strict >)
        # Entries at 5.5h,6.5h,7.5h are outside
        result = compute_rolling_window(entries, hours=5, now=now)
        assert result.total_cost == pytest.approx(2.50, abs=0.01)
        assert result.entry_count == 5

    def test_7d_window_includes_all(self):
        now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
        entries = self._make_entries(now)
        result = compute_rolling_window(entries, hours=7 * 24, now=now)
        assert result.total_cost == pytest.approx(4.00, abs=0.01)
        assert result.entry_count == 8

    def test_empty_entries(self):
        now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
        result = compute_rolling_window([], hours=5, now=now)
        assert result.total_cost == 0.0
        assert result.entry_count == 0


class TestSessionContributions:
class TestHookMain:
    def test_main_processes_stdin(self, sample_jsonl_path, tmp_path, monkeypatch):
        """hook main() should read stdin JSON and append to usage log."""
        import io
        from claude_spend.hook import main as hook_main

        log_path = str(tmp_path / "claude-spend" / "usage-log.jsonl")
        monkeypatch.setattr("claude_spend.hook.os.path.expanduser", lambda p: str(tmp_path / "claude-spend" / "usage-log.jsonl") if "usage-log" in p else p)

        stdin_data = json.dumps({
            "session_id": "test-sess",
            "transcript_path": sample_jsonl_path,
            "cwd": "/tmp",
        })
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin_data))
        monkeypatch.setenv("HOME", str(tmp_path))

        # Redirect the log path
        monkeypatch.setattr(
            "claude_spend.hook.os.path.expanduser",
            lambda p: str(tmp_path / p.lstrip("~/")) if p.startswith("~") else p,
        )
        hook_main()

        log_file = tmp_path / ".claude-spend" / "usage-log.jsonl"
        assert log_file.exists()
        entries = load_usage_log(str(log_file))
        assert len(entries) == 1
        assert entries[0].session_id == "test-sess"

    def test_main_handles_empty_stdin(self, monkeypatch):
        """hook main() should not crash on empty stdin."""
        import io
        from claude_spend.hook import main as hook_main
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        hook_main()  # should not raise


    def test_contributions_sum_to_window_total(self):
        now = datetime.now(timezone.utc)
        entries = [
            UsageEntry(
                ts=now - timedelta(hours=1), session_id="s1", message_id="m1",
                model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                cache_write_tokens=0, cache_read_tokens=0,
                estimated_cost=2.00, project="alpha",
            ),
            UsageEntry(
                ts=now - timedelta(hours=2), session_id="s2", message_id="m2",
                model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                cache_write_tokens=0, cache_read_tokens=0,
                estimated_cost=3.00, project="beta",
            ),
        ]
        contribs = compute_session_contributions(entries, hours=5)
        total_pct = sum(c.pct for c in contribs)
        assert total_pct == pytest.approx(1.0, abs=0.001)
        # s2 is $3/$5 = 60%, s1 is $2/$5 = 40%
        s1 = next(c for c in contribs if c.session_id == "s1")
        s2 = next(c for c in contribs if c.session_id == "s2")
        assert s1.pct == pytest.approx(0.40, abs=0.01)
        assert s2.pct == pytest.approx(0.60, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_spend.hook'`

- [ ] **Step 3: Implement hook.py**

```python
# claude_spend/hook.py
"""Stop hook: extract usage from session JSONL, log to ~/.claude-spend/usage-log.jsonl."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta

from claude_spend.data import PRICING, FALLBACK_MODEL, calculate_cost, TokenUsage


@dataclass
class UsageEntry:
    ts: datetime
    session_id: str
    message_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    estimated_cost: float
    project: str


@dataclass
class WindowSummary:
    total_cost: float
    entry_count: int
    entries: list[UsageEntry]


@dataclass
class SessionContribution:
    session_id: str
    project: str
    cost: float
    pct: float  # fraction of window total (0.0–1.0)


def extract_latest_usage(jsonl_path: str, session_id: str) -> UsageEntry | None:
    """Parse JSONL and return a UsageEntry for the last assistant message with usage."""
    if not os.path.isfile(jsonl_path):
        return None

    last_usage = None
    last_model = None
    last_msg_id = None

    try:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") != "assistant":
                    continue
                inner = msg.get("message", {})
                usage_raw = inner.get("usage")
                model = inner.get("model")
                msg_id = inner.get("id", "")
                if usage_raw and model:
                    last_usage = usage_raw
                    last_model = model
                    last_msg_id = msg_id
    except OSError:
        return None

    if last_usage is None:
        return None

    input_tokens = last_usage.get("input_tokens", 0)
    output_tokens = last_usage.get("output_tokens", 0)
    cache_write = last_usage.get("cache_creation_input_tokens", 0)
    cache_read = last_usage.get("cache_read_input_tokens", 0)

    usage = TokenUsage(input_tokens, output_tokens, cache_write, cache_read)
    cost = calculate_cost(usage, last_model)

    return UsageEntry(
        ts=datetime.now(timezone.utc),
        session_id=session_id,
        message_id=last_msg_id or "",
        model=last_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        estimated_cost=cost,
        project=os.path.basename(os.getcwd()),
    )


def _entry_dedup_key(entry: UsageEntry) -> str:
    return f"{entry.session_id}:{entry.message_id}"


def load_usage_log(log_path: str) -> list[UsageEntry]:
    """Load all entries from the usage log JSONL."""
    if not os.path.isfile(log_path):
        return []
    entries = []
    with open(log_path) as f:
        for line in f:
            try:
                raw = json.loads(line)
                entries.append(UsageEntry(
                    ts=datetime.fromisoformat(raw["ts"]),
                    session_id=raw["session_id"],
                    message_id=raw.get("message_id", ""),
                    model=raw["model"],
                    input_tokens=raw["input_tokens"],
                    output_tokens=raw["output_tokens"],
                    cache_write_tokens=raw.get("cache_write_tokens", 0),
                    cache_read_tokens=raw.get("cache_read_tokens", 0),
                    estimated_cost=raw["estimated_cost"],
                    project=raw.get("project", ""),
                ))
            except (json.JSONDecodeError, KeyError):
                continue
    return entries


def _tail_dedup_keys(log_path: str, n: int = 50) -> set[str]:
    """Read the last N lines of the log for dedup keys. O(1) vs O(n) full read."""
    if not os.path.isfile(log_path):
        return set()
    keys = set()
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)  # end of file
            size = f.tell()
            # Read last ~10KB (generous for 50 lines)
            read_size = min(size, 10240)
            f.seek(size - read_size)
            tail = f.read().decode("utf-8", errors="replace")
            lines = tail.strip().split("\n")
            for line in lines[-n:]:
                try:
                    raw = json.loads(line)
                    keys.add(f"{raw.get('session_id', '')}:{raw.get('message_id', '')}")
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return keys


def append_usage_entry(log_path: str, entry: UsageEntry) -> None:
    """Append entry to log, skipping if (session_id, message_id) seen in last 50 entries."""
    import fcntl

    dedup_key = _entry_dedup_key(entry)
    recent_keys = _tail_dedup_keys(log_path)
    if dedup_key in recent_keys:
        return

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    raw = {
        "ts": entry.ts.isoformat(),
        "session_id": entry.session_id,
        "message_id": entry.message_id,
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cache_write_tokens": entry.cache_write_tokens,
        "cache_read_tokens": entry.cache_read_tokens,
        "estimated_cost": entry.estimated_cost,
        "project": entry.project,
    }
    with open(log_path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(raw) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def compute_rolling_window(
    entries: list[UsageEntry], hours: int, now: datetime | None = None,
) -> WindowSummary:
    """Sum entries within the last `hours` hours. Pass `now` for deterministic tests."""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    in_window = [e for e in entries if e.ts > cutoff]  # strict > to avoid boundary ambiguity
    total = sum(e.estimated_cost for e in in_window)
    return WindowSummary(total_cost=total, entry_count=len(in_window), entries=in_window)


def compute_session_contributions(
    entries: list[UsageEntry], hours: int, now: datetime | None = None,
) -> list[SessionContribution]:
    """Compute each session's fractional contribution to a rolling window."""
    window = compute_rolling_window(entries, hours, now=now)
    if window.total_cost <= 0:
        return []

    by_session: dict[str, tuple[float, str]] = {}
    for e in window.entries:
        cost, proj = by_session.get(e.session_id, (0.0, e.project))
        by_session[e.session_id] = (cost + e.estimated_cost, proj)

    return [
        SessionContribution(
            session_id=sid,
            project=proj,
            cost=cost,
            pct=cost / window.total_cost,
        )
        for sid, (cost, proj) in by_session.items()
    ]


def _log_error(msg: str) -> None:
    """Append error to ~/.claude-spend/hook.log for debugging."""
    try:
        log_dir = os.path.expanduser("~/.claude-spend")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "hook.log"), "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except OSError:
        pass


def main() -> None:
    """Entry point when invoked as a Claude Code Stop hook via stdin."""
    try:
        raw = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError) as e:
        _log_error(f"stdin parse error: {e}")
        return

    session_id = raw.get("session_id", "")
    transcript_path = raw.get("transcript_path", "")

    if not session_id or not transcript_path:
        _log_error(f"missing session_id or transcript_path: {raw.keys()}")
        return

    entry = extract_latest_usage(transcript_path, session_id)
    if entry is None:
        _log_error(f"no usage found in {transcript_path}")
        return

    log_path = os.path.expanduser("~/.claude-spend/usage-log.jsonl")
    append_usage_entry(log_path, entry)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hook.py -v`
Expected: all 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/hook.py tests/test_hook.py
git commit -m "feat: add Stop hook data layer with usage log and rolling windows"
```

---

### Task 3: OAuth Usage API Client

**Files:**
- Create: `claude_spend/usage_api.py`
- Create: `tests/test_usage_api.py`

- [ ] **Step 1: Write failing tests for OAuth client**

```python
# tests/test_usage_api.py
"""Tests for OAuth usage API client and caching."""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from claude_spend.usage_api import (
    QuotaSnapshot, load_credentials_token, fetch_quota_snapshot,
    _parse_api_response, load_cached_snapshot, save_cached_snapshot,
    CACHE_TTL_SECONDS,
)


MOCK_API_RESPONSE = {
    "session": {"used_percent": 0.78, "reset_at": "2026-04-01T16:14:00Z"},
    "weekly": {"used_percent": 0.42, "reset_at": "2026-04-05T08:00:00Z"},
    "weekly_sonnet": {"used_percent": 0.18, "reset_at": "2026-04-05T08:00:00Z"},
}


class TestParseApiResponse:
    def test_parses_valid_response(self):
        snap = _parse_api_response(MOCK_API_RESPONSE)
        assert snap.session_pct == pytest.approx(0.78)
        assert snap.weekly_pct == pytest.approx(0.42)
        assert snap.sonnet_weekly_pct == pytest.approx(0.18)
        assert snap.session_reset_at.year == 2026

    def test_handles_missing_fields_gracefully(self):
        snap = _parse_api_response({"session": {"used_percent": 0.5}})
        assert snap.session_pct == pytest.approx(0.5)
        assert snap.weekly_pct == 0.0
        assert snap.sonnet_weekly_pct == 0.0
        assert snap.session_reset_at is None
        assert snap.weekly_reset_at is None


class TestCredentials:
    def test_loads_token_from_file(self, tmp_path):
        cred_path = tmp_path / ".credentials.json"
        cred_path.write_text(json.dumps({
            "claudeAiOauth": {"accessToken": "sk-test-token-123"}
        }))
        token = load_credentials_token(str(cred_path))
        assert token == "sk-test-token-123"

    def test_returns_none_for_missing_file(self, tmp_path):
        token = load_credentials_token(str(tmp_path / "nope.json"))
        assert token is None

    def test_returns_none_for_malformed_json(self, tmp_path):
        cred_path = tmp_path / ".credentials.json"
        cred_path.write_text("{bad json")
        token = load_credentials_token(str(cred_path))
        assert token is None

    def test_returns_none_for_missing_key_path(self, tmp_path):
        cred_path = tmp_path / ".credentials.json"
        cred_path.write_text(json.dumps({"other": "data"}))
        token = load_credentials_token(str(cred_path))
        assert token is None


class TestCaching:
    def test_save_and_load_cache(self, tmp_path):
        snap = _parse_api_response(MOCK_API_RESPONSE)
        cache_path = str(tmp_path / "quota-cache.json")
        save_cached_snapshot(cache_path, snap)
        loaded = load_cached_snapshot(cache_path)
        assert loaded is not None
        assert loaded.session_pct == pytest.approx(0.78)

    def test_expired_cache_returns_none(self, tmp_path):
        snap = _parse_api_response(MOCK_API_RESPONSE)
        cache_path = str(tmp_path / "quota-cache.json")
        save_cached_snapshot(cache_path, snap)
        # Manually backdate the cache file
        raw = json.loads(open(cache_path).read())
        raw["cached_at"] = (datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS + 10)).isoformat()
        with open(cache_path, "w") as f:
            json.dump(raw, f)
        loaded = load_cached_snapshot(cache_path)
        assert loaded is None

    def test_missing_cache_returns_none(self, tmp_path):
        loaded = load_cached_snapshot(str(tmp_path / "nope.json"))
        assert loaded is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_usage_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_spend.usage_api'`

- [ ] **Step 3: Implement usage_api.py**

```python
# claude_spend/usage_api.py
"""OAuth usage API client for Anthropic's undocumented quota endpoint."""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"
CACHE_TTL_SECONDS = 60
DEFAULT_CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
DEFAULT_CACHE_PATH = os.path.expanduser("~/.claude-spend/quota-cache.json")


@dataclass
class QuotaSnapshot:
    session_pct: float = 0.0            # 0.0–1.0
    weekly_pct: float = 0.0             # 0.0–1.0
    sonnet_weekly_pct: float = 0.0      # 0.0–1.0
    session_reset_at: datetime | None = None
    weekly_reset_at: datetime | None = None
    plan_name: str | None = None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_api_response(data: dict) -> QuotaSnapshot:
    """Parse the JSON response from the usage API into a QuotaSnapshot.

    WARNING: This parses an UNDOCUMENTED API. The schema is community-discovered
    and may change without notice. If the response shape changes, all percentages
    will silently default to 0.0.
    """
    if "session" not in data:
        import warnings
        warnings.warn(
            f"Unexpected OAuth usage API response shape. Keys: {list(data.keys())}. "
            "The API may have changed. Quota percentages will be inaccurate.",
            UserWarning,
            stacklevel=2,
        )
    session = data.get("session", {})
    weekly = data.get("weekly", {})
    sonnet = data.get("weekly_sonnet", {})

    return QuotaSnapshot(
        session_pct=session.get("used_percent", 0.0),
        weekly_pct=weekly.get("used_percent", 0.0),
        sonnet_weekly_pct=sonnet.get("used_percent", 0.0),
        session_reset_at=_parse_iso(session.get("reset_at")),
        weekly_reset_at=_parse_iso(weekly.get("reset_at")),
    )


def load_credentials_token(cred_path: str = DEFAULT_CREDENTIALS_PATH) -> str | None:
    """Read OAuth access token from Claude credentials file."""
    if not os.path.isfile(cred_path):
        return None
    try:
        with open(cred_path) as f:
            data = json.load(f)
        return data.get("claudeAiOauth", {}).get("accessToken")
    except (json.JSONDecodeError, OSError, AttributeError):
        return None


def save_cached_snapshot(cache_path: str, snap: QuotaSnapshot) -> None:
    """Write snapshot to cache file with timestamp."""
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    raw = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "session_pct": snap.session_pct,
        "weekly_pct": snap.weekly_pct,
        "sonnet_weekly_pct": snap.sonnet_weekly_pct,
        "session_reset_at": snap.session_reset_at.isoformat() if snap.session_reset_at else None,
        "weekly_reset_at": snap.weekly_reset_at.isoformat() if snap.weekly_reset_at else None,
        "plan_name": snap.plan_name,
    }
    with open(cache_path, "w") as f:
        json.dump(raw, f)


def load_cached_snapshot(cache_path: str = DEFAULT_CACHE_PATH) -> QuotaSnapshot | None:
    """Load snapshot from cache if it exists and is within TTL."""
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path) as f:
            raw = json.load(f)
        cached_at = datetime.fromisoformat(raw["cached_at"])
        if datetime.now(timezone.utc) - cached_at > timedelta(seconds=CACHE_TTL_SECONDS):
            return None
        return QuotaSnapshot(
            session_pct=raw.get("session_pct", 0.0),
            weekly_pct=raw.get("weekly_pct", 0.0),
            sonnet_weekly_pct=raw.get("sonnet_weekly_pct", 0.0),
            session_reset_at=_parse_iso(raw.get("session_reset_at")),
            weekly_reset_at=_parse_iso(raw.get("weekly_reset_at")),
            plan_name=raw.get("plan_name"),
        )
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def fetch_quota_snapshot(
    cred_path: str = DEFAULT_CREDENTIALS_PATH,
    cache_path: str = DEFAULT_CACHE_PATH,
) -> QuotaSnapshot | None:
    """Fetch quota snapshot: return cached if fresh, else call API. Returns None on any failure."""
    cached = load_cached_snapshot(cache_path)
    if cached is not None:
        return cached

    token = load_credentials_token(cred_path)
    if not token:
        return None

    try:
        req = urllib.request.Request(
            USAGE_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": BETA_HEADER,
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None

    snap = _parse_api_response(data)
    save_cached_snapshot(cache_path, snap)
    return snap
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_usage_api.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/usage_api.py tests/test_usage_api.py
git commit -m "feat: add OAuth usage API client with caching"
```

---

### Task 4: Unified Quota State

**Files:**
- Create: `claude_spend/quota.py`
- Create: `tests/test_quota.py`

This module merges OAuth + hook data into one `QuotaState` the dashboard consumes, implementing the priority logic from the spec.

- [ ] **Step 1: Write failing tests for QuotaState**

```python
# tests/test_quota.py
"""Tests for unified QuotaState that merges OAuth + hook data."""

from datetime import datetime, timezone, timedelta

import pytest

from claude_spend.quota import QuotaState, build_quota_state, DataSource
from claude_spend.usage_api import QuotaSnapshot
from claude_spend.hook import UsageEntry, WindowSummary
from claude_spend.plan_config import PlanBudget, PLAN_BUDGETS


class TestBuildQuotaState:
    def test_oauth_takes_priority(self):
        snap = QuotaSnapshot(
            session_pct=0.78, weekly_pct=0.42, sonnet_weekly_pct=0.18,
            session_reset_at=datetime(2026, 4, 1, 16, 0, tzinfo=timezone.utc),
            weekly_reset_at=datetime(2026, 4, 5, 8, 0, tzinfo=timezone.utc),
        )
        # Hook data exists but should be overridden for percentages
        now = datetime.now(timezone.utc)
        hook_entries = [
            UsageEntry(ts=now, session_id="s1", message_id="m1", model="claude-opus-4-6",
                       input_tokens=1000, output_tokens=200, cache_write_tokens=0,
                       cache_read_tokens=0, estimated_cost=2.00, project="test"),
        ]
        budget = PLAN_BUDGETS["max5"]
        state = build_quota_state(oauth_snapshot=snap, hook_entries=hook_entries, budget=budget)

        assert state.source == DataSource.OAUTH
        assert state.session_pct == pytest.approx(0.78)
        assert state.weekly_pct == pytest.approx(0.42)
        assert state.session_reset_at is not None

    def test_hook_fallback_when_no_oauth(self):
        now = datetime.now(timezone.utc)
        entries = [
            UsageEntry(ts=now - timedelta(hours=1), session_id="s1", message_id="m1",
                       model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                       cache_write_tokens=0, cache_read_tokens=0,
                       estimated_cost=4.40, project="test"),
        ]
        budget = PLAN_BUDGETS["max5"]  # 5h budget = $8.80
        state = build_quota_state(oauth_snapshot=None, hook_entries=entries, budget=budget)

        assert state.source == DataSource.HOOK
        assert state.session_pct == pytest.approx(4.40 / 8.80, abs=0.01)
        assert state.session_reset_at is None  # no reset info from hook

    def test_no_data_returns_empty_state(self):
        budget = PLAN_BUDGETS["pro"]
        state = build_quota_state(oauth_snapshot=None, hook_entries=[], budget=budget)
        assert state.source == DataSource.NONE
        assert state.session_pct == 0.0
        assert state.weekly_pct == 0.0

    def test_hook_estimated_cost_used(self):
        now = datetime.now(timezone.utc)
        entries = [
            UsageEntry(ts=now - timedelta(hours=1), session_id="s1", message_id="m1",
                       model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                       cache_write_tokens=0, cache_read_tokens=0,
                       estimated_cost=3.00, project="test"),
            UsageEntry(ts=now - timedelta(days=2), session_id="s2", message_id="m2",
                       model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                       cache_write_tokens=0, cache_read_tokens=0,
                       estimated_cost=7.00, project="test"),
        ]
        budget = PlanBudget(name="Test", five_hour_budget=10.0, weekly_budget=100.0, monthly_price=0)
        state = build_quota_state(oauth_snapshot=None, hook_entries=entries, budget=budget)

        # 5h: only s1 ($3.00) → 3/10 = 0.30
        assert state.session_pct == pytest.approx(0.30, abs=0.01)
        assert state.estimated_5h_cost == pytest.approx(3.00, abs=0.01)
        # 7d: s1 + s2 ($10.00) → 10/100 = 0.10
        assert state.weekly_pct == pytest.approx(0.10, abs=0.01)
        assert state.estimated_weekly_cost == pytest.approx(10.00, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_quota.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_spend.quota'`

- [ ] **Step 3: Implement quota.py**

```python
# claude_spend/quota.py
"""Unified QuotaState merging OAuth snapshot + hook estimates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from claude_spend.usage_api import QuotaSnapshot
from claude_spend.hook import UsageEntry, compute_rolling_window
from claude_spend.plan_config import PlanBudget


class DataSource(Enum):
    OAUTH = "oauth"
    HOOK = "hook"
    NONE = "none"


@dataclass
class QuotaState:
    source: DataSource
    session_pct: float = 0.0            # 0.0–1.0
    weekly_pct: float = 0.0
    sonnet_weekly_pct: float = 0.0
    session_reset_at: datetime | None = None
    weekly_reset_at: datetime | None = None
    estimated_5h_cost: float = 0.0      # $ used in current 5h window
    estimated_weekly_cost: float = 0.0  # $ used in current 7d window
    budget: PlanBudget | None = None


def build_quota_state(
    oauth_snapshot: QuotaSnapshot | None,
    hook_entries: list[UsageEntry],
    budget: PlanBudget,
) -> QuotaState:
    """Build a QuotaState preferring OAuth data, falling back to hook estimates."""
    # Compute hook windows regardless (used for cost estimates even with OAuth)
    window_5h = compute_rolling_window(hook_entries, hours=5)
    window_7d = compute_rolling_window(hook_entries, hours=7 * 24)

    if oauth_snapshot is not None:
        return QuotaState(
            source=DataSource.OAUTH,
            session_pct=oauth_snapshot.session_pct,
            weekly_pct=oauth_snapshot.weekly_pct,
            sonnet_weekly_pct=oauth_snapshot.sonnet_weekly_pct,
            session_reset_at=oauth_snapshot.session_reset_at,
            weekly_reset_at=oauth_snapshot.weekly_reset_at,
            estimated_5h_cost=window_5h.total_cost,
            estimated_weekly_cost=window_7d.total_cost,
            budget=budget,
        )

    if hook_entries:
        session_pct = min(1.0, window_5h.total_cost / budget.five_hour_budget) if budget.five_hour_budget > 0 else 0.0
        weekly_pct = min(1.0, window_7d.total_cost / budget.weekly_budget) if budget.weekly_budget > 0 else 0.0

        return QuotaState(
            source=DataSource.HOOK,
            session_pct=session_pct,
            weekly_pct=weekly_pct,
            sonnet_weekly_pct=0.0,  # can't distinguish models from hook alone
            estimated_5h_cost=window_5h.total_cost,
            estimated_weekly_cost=window_7d.total_cost,
            budget=budget,
        )

    return QuotaState(source=DataSource.NONE, budget=budget)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_quota.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/quota.py tests/test_quota.py
git commit -m "feat: add unified QuotaState merging OAuth + hook data"
```

---

### Task 5: Hook Install / Uninstall CLI

**Files:**
- Create: `claude_spend/hook_install.py`
- Create: `tests/test_hook_install.py`
- Modify: `pyproject.toml` (add CLI entry points)

- [ ] **Step 1: Write failing tests for install/uninstall**

```python
# tests/test_hook_install.py
"""Tests for hook installation and uninstallation into ~/.claude/settings.json."""

import json
import os

import pytest

from claude_spend.hook_install import (
    install_hook, uninstall_hook, is_hook_installed, HOOK_COMMAND,
)


@pytest.fixture
def claude_dir(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    return str(d)


@pytest.fixture
def settings_path(claude_dir):
    return os.path.join(claude_dir, "settings.json")


class TestInstallHook:
    def test_install_fresh_no_settings(self, claude_dir, settings_path):
        result = install_hook(claude_dir)
        assert result == "installed"
        assert os.path.isfile(settings_path)
        with open(settings_path) as f:
            data = json.load(f)
        hooks = data["hooks"]["Stop"]
        assert any(HOOK_COMMAND in h.get("command", "") for h in hooks)

    def test_install_preserves_existing_hooks(self, claude_dir, settings_path):
        existing = {
            "model": "opus",
            "hooks": {
                "Stop": [{"type": "command", "command": "echo done"}],
            },
        }
        with open(settings_path, "w") as f:
            json.dump(existing, f)

        install_hook(claude_dir)
        with open(settings_path) as f:
            data = json.load(f)
        hooks = data["hooks"]["Stop"]
        assert len(hooks) == 2
        assert hooks[0]["command"] == "echo done"  # original preserved
        assert data["model"] == "opus"  # other settings preserved

    def test_install_preserves_existing_non_stop_hooks(self, claude_dir, settings_path):
        existing = {
            "hooks": {
                "PreToolUse": [{"type": "command", "command": "echo pre"}],
            },
        }
        with open(settings_path, "w") as f:
            json.dump(existing, f)

        install_hook(claude_dir)
        with open(settings_path) as f:
            data = json.load(f)
        assert data["hooks"]["PreToolUse"] == [{"type": "command", "command": "echo pre"}]
        assert any(HOOK_COMMAND in h.get("command", "") for h in data["hooks"]["Stop"])

    def test_install_idempotent(self, claude_dir, settings_path):
        install_hook(claude_dir)
        result = install_hook(claude_dir)
        assert result == "already_installed"
        with open(settings_path) as f:
            data = json.load(f)
        # Should only appear once
        stop_hooks = data["hooks"]["Stop"]
        claude_spend_hooks = [h for h in stop_hooks if HOOK_COMMAND in h.get("command", "")]
        assert len(claude_spend_hooks) == 1


class TestUninstallHook:
    def test_uninstall_removes_hook(self, claude_dir, settings_path):
        install_hook(claude_dir)
        assert is_hook_installed(claude_dir)
        result = uninstall_hook(claude_dir)
        assert result == "uninstalled"
        assert not is_hook_installed(claude_dir)

    def test_uninstall_preserves_other_hooks(self, claude_dir, settings_path):
        existing = {
            "hooks": {
                "Stop": [
                    {"type": "command", "command": "echo done"},
                ],
            },
        }
        with open(settings_path, "w") as f:
            json.dump(existing, f)
        install_hook(claude_dir)
        uninstall_hook(claude_dir)
        with open(settings_path) as f:
            data = json.load(f)
        assert len(data["hooks"]["Stop"]) == 1
        assert data["hooks"]["Stop"][0]["command"] == "echo done"

    def test_uninstall_noop_when_not_installed(self, claude_dir, settings_path):
        result = uninstall_hook(claude_dir)
        assert result == "not_installed"


class TestIsHookInstalled:
    def test_returns_false_no_settings(self, claude_dir):
        assert not is_hook_installed(claude_dir)

    def test_returns_true_after_install(self, claude_dir):
        install_hook(claude_dir)
        assert is_hook_installed(claude_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hook_install.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_spend.hook_install'`

- [ ] **Step 3: Implement hook_install.py**

```python
# claude_spend/hook_install.py
"""Install/uninstall the claude-spend Stop hook in ~/.claude/settings.json."""

from __future__ import annotations

import json
import os

HOOK_COMMAND = "python3 -m claude_spend.hook"


def _settings_path(claude_dir: str) -> str:
    return os.path.join(claude_dir, "settings.json")


def _load_settings(claude_dir: str) -> dict:
    path = _settings_path(claude_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(claude_dir: str, data: dict) -> None:
    path = _settings_path(claude_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def is_hook_installed(claude_dir: str) -> bool:
    """Check if the claude-spend Stop hook is already installed."""
    settings = _load_settings(claude_dir)
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    return any(HOOK_COMMAND in h.get("command", "") for h in stop_hooks)


def install_hook(claude_dir: str) -> str:
    """Install Stop hook. Returns 'installed' or 'already_installed'."""
    if is_hook_installed(claude_dir):
        return "already_installed"

    settings = _load_settings(claude_dir)
    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])
    stop_hooks.append({"type": "command", "command": HOOK_COMMAND})
    _save_settings(claude_dir, settings)

    # Create data directory
    data_dir = os.path.expanduser("~/.claude-spend")
    os.makedirs(data_dir, exist_ok=True)

    return "installed"


def uninstall_hook(claude_dir: str) -> str:
    """Remove Stop hook. Returns 'uninstalled' or 'not_installed'."""
    if not is_hook_installed(claude_dir):
        return "not_installed"

    settings = _load_settings(claude_dir)
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    settings["hooks"]["Stop"] = [
        h for h in stop_hooks if HOOK_COMMAND not in h.get("command", "")
    ]
    _save_settings(claude_dir, settings)
    return "uninstalled"


def main_install() -> None:
    """CLI entry point for `claude-spend install-hook`."""
    claude_dir = os.path.expanduser("~/.claude")
    result = install_hook(claude_dir)
    if result == "installed":
        print("Hook installed. Usage tracking is now active across all projects.")
    else:
        print("Hook is already installed.")


def main_uninstall() -> None:
    """CLI entry point for `claude-spend uninstall-hook`."""
    claude_dir = os.path.expanduser("~/.claude")
    result = uninstall_hook(claude_dir)
    if result == "uninstalled":
        print("Hook removed. Usage tracking is now disabled.")
    else:
        print("No hook found, nothing to remove.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hook_install.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Add CLI entry points to pyproject.toml**

In `pyproject.toml`, change the `[project.scripts]` section:

```toml
[project.scripts]
claude-monitor = "claude_spend.dashboard:main"
claude-spend-install-hook = "claude_spend.hook_install:main_install"
claude-spend-uninstall-hook = "claude_spend.hook_install:main_uninstall"
```

- [ ] **Step 6: Commit**

```bash
git add claude_spend/hook_install.py tests/test_hook_install.py pyproject.toml
git commit -m "feat: add hook install/uninstall CLI commands"
```

---

### Task 6: QuotaGauge and QuotaCard Widgets

**Files:**
- Modify: `claude_spend/dashboard.py`
- Modify: `tests/test_dashboard.py`
- Create: `tests/screenshots/` (directory for visual validation)

These are the reusable UI components used in both Overview and Limits tabs.

- [ ] **Step 1: Write failing tests for QuotaGauge widget rendering**

Add to `tests/test_dashboard.py`:

```python
# --- Quota widget tests ---

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
    content = str(gauge.render())
    assert "green" in content


def test_quota_gauge_color_red():
    from claude_spend.dashboard import QuotaGauge
    gauge = QuotaGauge("Test", pct=0.90)
    content = str(gauge.render())
    assert "red" in content


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_dashboard.py::test_quota_gauge_renders_bar_and_pct -v`
Expected: FAIL — `ImportError: cannot import name 'QuotaGauge' from 'claude_spend.dashboard'`

- [ ] **Step 3: Implement QuotaGauge and QuotaCard in dashboard.py**

Add after the `BigNumber` class (around line 425 in `dashboard.py`):

```python
class QuotaGauge(Static):
    """Compact progress bar gauge for quota display."""

    def __init__(self, label: str, pct: float = 0.0, reset_label: str = "", estimated: bool = False, **kwargs):
        self._label = label
        self._pct = min(1.0, max(0.0, pct))
        self._reset_label = reset_label
        self._estimated = estimated
        markup = self._build_markup()
        super().__init__(markup, **kwargs)

    def _build_markup(self) -> str:
        pct = self._pct
        pct_display = round(pct * 100)
        bar_width = 10
        fill = int(pct * bar_width)
        color = "green" if pct < 0.60 else "dark_orange" if pct < 0.85 else "red"
        bar = f"[{color}]" + "\u2588" * fill + f"[/{color}]" + "[dim]\u2591[/dim]" * (bar_width - fill)
        prefix = "~" if self._estimated else ""
        line1 = f"[dim]{self._label}[/dim]"
        line2 = f"{bar} [{color}]{prefix}{pct_display}%[/{color}]"
        line3 = f"[dim]Resets: {self._reset_label}[/dim]" if self._reset_label else ""
        parts = [line1, line2]
        if line3:
            parts.append(line3)
        return "\n".join(parts)

    def update_pct(self, pct: float, reset_label: str = "", estimated: bool = False) -> None:
        self._pct = min(1.0, max(0.0, pct))
        self._reset_label = reset_label
        self._estimated = estimated
        self.update(self._build_markup())


class QuotaCard(Static):
    """Bordered quota card for the Limits tab with title, bar, reset, cost."""

    def __init__(self, title: str, pct: float = 0.0, reset_label: str = "",
                 used: float = 0.0, budget: float = 0.0, estimated: bool = False, **kwargs):
        self._title = title
        self._pct = min(1.0, max(0.0, pct))
        self._reset_label = reset_label
        self._used = used
        self._budget = budget
        self._estimated = estimated
        markup = self._build_markup()
        super().__init__(markup, **kwargs)

    def _build_markup(self) -> str:
        pct = self._pct
        pct_display = round(pct * 100)
        bar_width = 20
        fill = int(pct * bar_width)
        color = "green" if pct < 0.60 else "dark_orange" if pct < 0.85 else "red"
        bar = f"[{color}]" + "\u2588" * fill + f"[/{color}]" + "[dim]\u2591[/dim]" * (bar_width - fill)
        prefix = "~" if self._estimated else ""

        lines = [
            f"[bold]{self._title}[/bold]",
            f"  {bar} [{color}]{prefix}{pct_display}%[/{color}]",
        ]
        if self._reset_label:
            lines.append(f"  [dim]Resets in {self._reset_label}[/dim]")
        lines.append(f"  [dim]Used: ~${self._used:.2f} / ~${self._budget:.2f}[/dim]")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_dashboard.py::test_quota_gauge_renders_bar_and_pct tests/test_dashboard.py::test_quota_gauge_color_green tests/test_dashboard.py::test_quota_gauge_color_red tests/test_dashboard.py::test_quota_gauge_clamps_above_1 tests/test_dashboard.py::test_quota_card_renders_all_parts -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: add QuotaGauge and QuotaCard widgets"
```

---

### Task 7: Overview Tab — Quota Gauge Row

**Files:**
- Modify: `claude_spend/dashboard.py` (compose, CSS, on_mount, data loading)
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing test for overview quota gauges**

Add to `tests/test_dashboard.py`:

```python
@pytest.mark.asyncio
async def test_overview_quota_gauges_render():
    """Overview tab should show 3 QuotaGauge widgets when quota data is provided."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard.py::test_overview_quota_gauges_render -v`
Expected: FAIL — `SpendApp.__init__() got an unexpected keyword argument 'quota_state'`

- [ ] **Step 3: Wire quota into SpendApp**

Modify `SpendApp.__init__` (line 505) to accept an optional `QuotaState`:

```python
def __init__(self, data: DashboardData, days_label: str, quota_state: QuotaState | None = None):
    super().__init__()
    self.data = data
    self.days_label = days_label
    self.quota_state = quota_state
    self._sort_state: dict[str, tuple[str, bool]] = {}
```

Add import at top of file:

```python
from claude_spend.quota import QuotaState, DataSource
```

Add CSS for quota containers (inside the `CSS = """` block):

```css
#overview-quota {
    height: auto;
    max-height: 5;
}
#overview-quota QuotaGauge {
    width: 1fr;
    padding: 0 2;
}
#overview-plan-label {
    height: auto;
    text-align: center;
    margin: 0 0 1 0;
}
```

In `compose()`, after the `#overview-numbers` Horizontal block (after line 533), add:

```python
                if self.quota_state and self.quota_state.source != DataSource.NONE:
                    qs = self.quota_state
                    estimated = qs.source == DataSource.HOOK
                    reset_5h = self._fmt_reset(qs.session_reset_at) if qs.session_reset_at else ""
                    reset_7d = self._fmt_reset(qs.weekly_reset_at) if qs.weekly_reset_at else ""
                    with Horizontal(id="overview-quota"):
                        yield QuotaGauge("5h Window", pct=qs.session_pct, reset_label=reset_5h, estimated=estimated)
                        yield QuotaGauge("Weekly Quota", pct=qs.weekly_pct, reset_label=reset_7d, estimated=estimated)
                        if qs.sonnet_weekly_pct > 0:
                            yield QuotaGauge("Sonnet Weekly", pct=qs.sonnet_weekly_pct, reset_label=reset_7d, estimated=estimated)
                    plan_label = qs.budget.name if qs.budget else "Unknown"
                    price = f"${qs.budget.monthly_price}/mo" if qs.budget and qs.budget.monthly_price else ""
                    yield Static(f"[dim]Plan: {plan_label} ({price})[/dim]", id="overview-plan-label")
```

Add the `_fmt_reset` helper method to `SpendApp`:

```python
@staticmethod
def _fmt_reset(reset_at: datetime | None) -> str:
    """Format a reset timestamp as a human-readable countdown."""
    if not reset_at:
        return ""
    now = datetime.now(timezone.utc)
    delta = reset_at - now
    if delta.total_seconds() <= 0:
        return "now"
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    if hours >= 24:
        days = hours // 24
        hours = hours % 24
        return f"{days}d {hours}h"
    return f"{hours}h {minutes:02d}m"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dashboard.py::test_overview_quota_gauges_render -v`
Expected: PASS

- [ ] **Step 5: Visual validation — screenshot the overview tab**

Add a screenshot test:

```python
@pytest.mark.asyncio
async def test_overview_quota_visual(tmp_path):
    """Visual validation: screenshot Overview tab with quota gauges."""
    from claude_spend.dashboard import SpendApp
    from claude_spend.quota import QuotaState, DataSource
    from claude_spend.plan_config import PLAN_BUDGETS

    data = _make_test_data()
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.78, weekly_pct=0.42,
        sonnet_weekly_pct=0.0, estimated_5h_cost=6.86, estimated_weekly_cost=42.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screenshot_path = str(tmp_path / "overview_quota.svg")
        app.save_screenshot(screenshot_path)
        assert os.path.isfile(screenshot_path)
```

Run: `python3 -m pytest tests/test_dashboard.py::test_overview_quota_visual -v`
Expected: PASS, screenshot saved. **Open the SVG to verify gauges appear correctly.**

- [ ] **Step 6: Run full test suite to ensure no regressions**

Run: `python3 -m pytest tests/ -v`
Expected: all tests PASS (previous tests like `test_app_mounts_with_data` still work because `quota_state` defaults to `None`)

- [ ] **Step 7: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: add quota gauge row to Overview tab"
```

---

### Task 8: Limits Tab — Layout and Data

**Files:**
- Modify: `claude_spend/dashboard.py`
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing test for Limits tab**

Add to `tests/test_dashboard.py`:

```python
@pytest.mark.asyncio
async def test_limits_tab_renders_with_quota():
    """Limits tab should render QuotaCards and recent sessions table."""
    from claude_spend.dashboard import SpendApp, QuotaCard
    from claude_spend.quota import QuotaState, DataSource
    from claude_spend.plan_config import PLAN_BUDGETS
    from textual.widgets import DataTable

    data = _make_test_data()
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.78, weekly_pct=0.42,
        sonnet_weekly_pct=0.0, estimated_5h_cost=6.86, estimated_weekly_cost=42.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)
    async with app.run_test(size=(120, 40)) as pilot:
        cards = app.query("QuotaCard")
        assert len(cards) >= 2  # at least 5h + weekly
        limits_table = app.query_one("#limits-sessions-table", DataTable)
        assert limits_table.row_count >= 1


@pytest.mark.asyncio
async def test_limits_tab_no_data_shows_fallback():
    """Limits tab should show setup message when no quota data."""
    from claude_spend.dashboard import SpendApp

    data = _make_test_data()
    app = SpendApp(data, "Last 7 days", quota_state=None)
    async with app.run_test(size=(120, 40)) as pilot:
        # Switch to Limits tab
        tabs = app.query("Tab")
        for tab in tabs:
            if "Limits" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()
        no_data = app.query_one("#no-limits-data")
        assert no_data is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_dashboard.py::test_limits_tab_renders_with_quota -v`
Expected: FAIL — no Limits tab exists yet

- [ ] **Step 3: Add Limits tab to compose()**

In `compose()`, change the `TabbedContent` line (line 522) to add "Limits":

```python
with TabbedContent("Overview", "Effectiveness", "Sessions", "Limits", "Projects", "Models", "Subagents", "Skills"):
```

Add the Limits tab pane after the Sessions tab pane (after line 590):

```python
            with TabPane("Limits", id="tab-limits"):
                if self.quota_state and self.quota_state.source != DataSource.NONE:
                    qs = self.quota_state
                    estimated = qs.source == DataSource.HOOK
                    budget = qs.budget
                    plan_label = budget.name if budget else "Unknown"
                    price = f"${budget.monthly_price}/mo" if budget and budget.monthly_price else ""
                    yield Static(f"[bold]Plan: {plan_label}[/bold]  [dim]({price})[/dim]", id="limits-plan-label")

                    reset_5h = self._fmt_reset(qs.session_reset_at) if qs.session_reset_at else ""
                    reset_7d = self._fmt_reset(qs.weekly_reset_at) if qs.weekly_reset_at else ""
                    with Horizontal(id="limits-cards"):
                        yield QuotaCard(
                            title="5h Session Window", pct=qs.session_pct,
                            reset_label=reset_5h, used=qs.estimated_5h_cost,
                            budget=budget.five_hour_budget if budget else 0,
                            estimated=estimated,
                        )
                        yield QuotaCard(
                            title="Weekly All Models", pct=qs.weekly_pct,
                            reset_label=reset_7d, used=qs.estimated_weekly_cost,
                            budget=budget.weekly_budget if budget else 0,
                            estimated=estimated,
                        )
                        if qs.sonnet_weekly_pct > 0:
                            yield QuotaCard(
                                title="Weekly Sonnet", pct=qs.sonnet_weekly_pct,
                                reset_label=reset_7d, used=0.0, budget=0.0,
                                estimated=estimated,
                            )
                    yield Static("[#666666]Recent sessions contributing to current windows[/#666666]", classes="table-help")
                    yield DataTable(id="limits-sessions-table")
                    yield PlotextPlot(id="limits-history-chart")
                else:
                    yield Static(
                        "[dim]No usage data. Run `claude-spend-install-hook` to track usage, "
                        "or login with `claude login` for real-time quota.[/dim]",
                        id="no-limits-data",
                    )
```

Add CSS for Limits tab:

```css
#limits-plan-label {
    height: auto;
    margin: 0 1;
    padding: 0 1;
}
#limits-cards {
    height: auto;
    max-height: 8;
}
#limits-cards QuotaCard {
    width: 1fr;
    padding: 0 1;
    border: tall $surface-lighten-2;
}
```

Add `_populate_limits_table` method and call it from `on_mount`:

```python
def _populate_limits_table(self) -> None:
    """Populate the Limits tab recent sessions table."""
    if not self.quota_state or self.quota_state.source == DataSource.NONE:
        return
    try:
        table = self.query_one("#limits-sessions-table", DataTable)
    except Exception:
        return

    table.add_columns("Time", "Project", "Cost", "5h%", "7d%")

    now = datetime.now(timezone.utc)
    cutoff_5h = now - timedelta(hours=5)
    cutoff_7d = now - timedelta(days=7)
    budget = self.quota_state.budget

    # Use session data for the table
    recent = [s for s in self.data.sessions if s.start_time >= cutoff_7d]
    total_5h_cost = sum(s.estimated_cost for s in recent if s.start_time >= cutoff_5h)
    total_7d_cost = sum(s.estimated_cost for s in recent)

    for s in recent[:20]:
        # Relative time
        delta = now - s.start_time
        if delta.total_seconds() < 86400:
            time_label = s.start_time.strftime("%H:%M")
        elif delta.days == 1:
            time_label = "yesterday"
        else:
            time_label = f"{delta.days}d ago"

        in_5h = s.start_time >= cutoff_5h
        # Show session's share of budget (not share of observed spend)
        pct_5h_val = (s.estimated_cost / budget.five_hour_budget * 100) if in_5h and budget and budget.five_hour_budget > 0 else 0
        pct_5h = f"{pct_5h_val:.0f}%" if in_5h else "—"
        pct_7d_val = (s.estimated_cost / budget.weekly_budget * 100) if budget and budget.weekly_budget > 0 else 0
        pct_7d = f"{pct_7d_val:.1f}%"

        table.add_row(time_label, s.project_name, _fmt_cost(s.estimated_cost), pct_5h, pct_7d)
```

In `on_mount`, add `self._populate_limits_table()` after the other table populators.

Update `on_tabbed_content_tab_activated` to handle `tab-limits` chart:

```python
chart_populators = {
    "tab-sessions": self._populate_sessions_heatmap,
    "tab-models": self._populate_models_chart,
    "tab-subagents": self._populate_subagents_chart,
    "tab-skills": self._populate_skills_chart,
    "tab-limits": self._populate_limits_chart,
}
```

Add a minimal `_populate_limits_chart`:

```python
def _populate_limits_chart(self) -> None:
    """Populate historical quota utilization chart (placeholder until enough data)."""
    try:
        chart_widget = self.query_one("#limits-history-chart", PlotextPlot)
    except Exception:
        return
    plt = chart_widget.plt
    plt.title("Daily Peak 5h Quota (estimated)")
    plt.xlabel("Date")
    plt.ylabel("% of 5h budget")

    if not self.quota_state or not self.quota_state.budget:
        plt.text("Accumulating data...", x=0.5, y=0.5)
        return

    budget_5h = self.quota_state.budget.five_hour_budget
    if budget_5h <= 0:
        return

    # Compute daily peak 5h sliding window cost from session data.
    # For each day, find the maximum cost in any 5h contiguous window.
    now = datetime.now(timezone.utc)
    sessions_by_date: dict[str, list[SessionSummary]] = {}
    for s in self.data.sessions:
        date_str = s.start_time.strftime("%m/%d")
        sessions_by_date.setdefault(date_str, []).append(s)

    if len(sessions_by_date) < 2:
        plt.text("Need 2+ days of data", x=0.5, y=0.5)
        return

    daily_peaks: dict[str, float] = {}
    for date_str, day_sessions in sessions_by_date.items():
        # Slide a 5h window across the day's sessions
        sorted_sessions = sorted(day_sessions, key=lambda s: s.start_time)
        max_cost = 0.0
        for anchor in sorted_sessions:
            window_end = anchor.start_time + timedelta(hours=5)
            window_cost = sum(
                s.estimated_cost for s in sorted_sessions
                if anchor.start_time <= s.start_time < window_end
            )
            max_cost = max(max_cost, window_cost)
        daily_peaks[date_str] = max_cost

    dates = sorted(daily_peaks.keys())
    pcts = [min(100, daily_peaks[d] / budget_5h * 100) for d in dates]

    plt.bar(dates, pcts, width=0.8)
    plt.ylim(0, max(100, max(pcts) * 1.1))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_dashboard.py::test_limits_tab_renders_with_quota tests/test_dashboard.py::test_limits_tab_no_data_shows_fallback -v`
Expected: both PASS

- [ ] **Step 5: Visual validation — screenshot the Limits tab**

```python
@pytest.mark.asyncio
async def test_limits_tab_visual(tmp_path):
    """Visual validation: screenshot Limits tab."""
    from claude_spend.dashboard import SpendApp
    from claude_spend.quota import QuotaState, DataSource
    from claude_spend.plan_config import PLAN_BUDGETS

    data = _make_test_data()
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.78, weekly_pct=0.42,
        sonnet_weekly_pct=0.0, estimated_5h_cost=6.86, estimated_weekly_cost=42.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)
    async with app.run_test(size=(120, 40)) as pilot:
        tabs = app.query("Tab")
        for tab in tabs:
            if "Limits" in str(tab.label):
                await pilot.click(type(tab), offset=(2, 0))
                break
        await pilot.pause()
        screenshot_path = str(tmp_path / "limits_tab.svg")
        app.save_screenshot(screenshot_path)
        assert os.path.isfile(screenshot_path)
```

Run: `python3 -m pytest tests/test_dashboard.py::test_limits_tab_visual -v`
Expected: PASS. **Open the SVG to verify QuotaCards, table, and chart.**

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS. Update any tests that assert BigNumber count or tab count if they changed (e.g., `test_app_mounts_with_data` may need the tab count updated, and `test_table_help_widgets_exist` count may change).

- [ ] **Step 7: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: add dedicated Limits tab with quota cards and sessions table"
```

---

### Task 9: Session Detail — PLAN USAGE Line

**Files:**
- Modify: `claude_spend/dashboard.py` (`_build_session_detail` method)
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_dashboard.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard.py::test_session_detail_shows_plan_usage -v`
Expected: FAIL — "PLAN USAGE" not in content

- [ ] **Step 3: Add PLAN USAGE line to _build_session_detail**

In `_build_session_detail` (around line 1073, before `return "\n".join(lines)`), add:

```python
        # Plan usage
        if self.quota_state and self.quota_state.source != DataSource.NONE and self.quota_state.budget:
            budget = self.quota_state.budget
            # Session's share of 5h window
            now = datetime.now(timezone.utc)
            cutoff_5h = now - timedelta(hours=5)
            cutoff_7d = now - timedelta(days=7)
            total_5h = sum(s.estimated_cost for s in self.data.sessions if s.start_time >= cutoff_5h)
            total_7d = sum(s.estimated_cost for s in self.data.sessions if s.start_time >= cutoff_7d)

            session_5h_pct = session.estimated_cost / total_5h if total_5h > 0 and session.start_time >= cutoff_5h else 0.0
            session_7d_pct = session.estimated_cost / total_7d if total_7d > 0 and session.start_time >= cutoff_7d else 0.0

            # Scale by overall window utilization
            effective_5h = session_5h_pct * self.quota_state.session_pct
            effective_7d = session_7d_pct * self.quota_state.weekly_pct

            bar_w = 5
            fill_5h = int(effective_5h * bar_w)
            fill_7d = int(effective_7d * bar_w)
            bar_5h = "[green]" + "\u2588" * fill_5h + "[/green]" + "[dim]\u2591[/dim]" * (bar_w - fill_5h)
            bar_7d = "[green]" + "\u2588" * fill_7d + "[/green]" + "[dim]\u2591[/dim]" * (bar_w - fill_7d)

            lines.append("")
            lines.append(
                f"[dim]PLAN USAGE[/dim]  5h: {bar_5h} {effective_5h * 100:.0f}% of window   "
                f"7d: {bar_7d} {effective_7d * 100:.1f}% of weekly"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dashboard.py::test_session_detail_shows_plan_usage -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: add PLAN USAGE line to session detail panel"
```

---

### Task 10: Wire Data Loading into main()

**Files:**
- Modify: `claude_spend/dashboard.py` (`main()` function)
- Add: `--plan` CLI argument

- [ ] **Step 1: Write a test for the CLI plan argument**

Add to `tests/test_dashboard.py`:

```python
def test_main_accepts_plan_arg(monkeypatch):
    """main() should accept --plan argument without crashing."""
    import sys
    from unittest.mock import patch, MagicMock

    monkeypatch.setattr(sys, "argv", ["claude-monitor", "--days", "7", "--plan", "pro"])
    # Mock load_all and SpendApp.run to avoid actual execution
    with patch("claude_spend.dashboard.load_all") as mock_load, \
         patch("claude_spend.dashboard.SpendApp") as MockApp:
        mock_load.return_value = MagicMock()
        mock_instance = MockApp.return_value
        mock_instance.run = MagicMock()
        # Need to mock os.path.isdir to avoid sys.exit
        with patch("os.path.isdir", return_value=True):
            from claude_spend.dashboard import main
            main()
        # Verify SpendApp was called with a quota_state argument
        call_kwargs = MockApp.call_args
        assert "quota_state" in str(call_kwargs) or len(call_kwargs.args) >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard.py::test_main_accepts_plan_arg -v`
Expected: FAIL — `main()` doesn't accept `--plan`

- [ ] **Step 3: Update main() to load quota data**

Replace the `main()` function (lines 1117–1144):

```python
def main():
    parser = argparse.ArgumentParser(description="Claude Spend — Token usage dashboard")
    parser.add_argument("--days", default="30", help="Number of days to show, or 'all'")
    parser.add_argument("--plan", default=None, help="Plan tier: pro, max5, max20")
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

    # Load quota state
    from claude_spend.plan_config import get_active_budget, save_plan_config, load_plan_config, DEFAULT_PLAN
    from claude_spend.usage_api import fetch_quota_snapshot
    from claude_spend.hook import load_usage_log
    from claude_spend.quota import build_quota_state

    config_dir = os.path.expanduser("~/.claude-spend")
    if args.plan:
        current = load_plan_config(config_dir)
        if current["plan"] != args.plan:
            save_plan_config(config_dir, plan=args.plan)

    budget = get_active_budget(config_dir)
    oauth_snap = fetch_quota_snapshot()
    log_path = os.path.join(config_dir, "usage-log.jsonl")
    hook_entries = load_usage_log(log_path)
    quota_state = build_quota_state(oauth_snap, hook_entries, budget)

    app = SpendApp(data, days_label, quota_state=quota_state)
    app.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dashboard.py::test_main_accepts_plan_arg -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add claude_spend/dashboard.py tests/test_dashboard.py
git commit -m "feat: wire quota data loading into main() with --plan CLI arg"
```

---

### Task 11: Full Integration Visual Validation

**Files:**
- Add: `tests/test_limits_tab.py` (dedicated integration test file)

This task does an end-to-end visual validation of all quota features working together.

- [ ] **Step 1: Write integration tests with visual validation**

```python
# tests/test_limits_tab.py
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
    """Build sessions that span multiple time windows for realistic testing."""
    now = datetime.now(timezone.utc)
    sessions = []
    # 3 sessions today (in 5h window)
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
    # 2 sessions from yesterday (in 7d window, outside 5h)
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
    """Full integration: OAuth data → Overview gauges + Limits tab + session detail."""
    from claude_spend.dashboard import SpendApp, QuotaGauge, QuotaCard
    from textual.widgets import DataTable, Static

    sessions = _make_sessions_across_windows()
    data = _make_data(sessions)
    snap = QuotaSnapshot(
        session_pct=0.65, weekly_pct=0.35, sonnet_weekly_pct=0.12,
        session_reset_at=datetime.now(timezone.utc) + timedelta(hours=2, minutes=14),
        weekly_reset_at=datetime.now(timezone.utc) + timedelta(days=4, hours=6),
    )
    quota = build_quota_state(snap, [], PLAN_BUDGETS["max5"])
    app = SpendApp(data, "Last 7 days", quota_state=quota)

    async with app.run_test(size=(140, 50)) as pilot:
        # Overview tab should have gauges
        gauges = app.query("QuotaGauge")
        assert len(gauges) >= 2

        # Switch to Limits tab
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

        # Screenshot
        app.save_screenshot(str(tmp_path / "limits_oauth.svg"))
        assert os.path.isfile(str(tmp_path / "limits_oauth.svg"))


@pytest.mark.asyncio
async def test_full_limits_hook_only_mode(tmp_path):
    """Full integration: hook-only data → estimated percentages with ~ prefix."""
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
        # Hook-only gauges should show estimated prefix
        gauge_content = str(gauges.first().render())
        assert "~" in gauge_content

        app.save_screenshot(str(tmp_path / "limits_hook.svg"))


@pytest.mark.asyncio
async def test_full_limits_no_data_mode(tmp_path):
    """Full integration: no data → shows setup instructions."""
    from claude_spend.dashboard import SpendApp

    sessions = _make_sessions_across_windows()
    data = _make_data(sessions)
    app = SpendApp(data, "Last 7 days", quota_state=None)

    async with app.run_test(size=(140, 50)) as pilot:
        # Switch to Limits tab
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
    """Session detail PLAN USAGE line shows correct proportional values."""
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
        # Switch to Sessions tab and select a row
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
```

- [ ] **Step 2: Run integration tests**

Run: `python3 -m pytest tests/test_limits_tab.py -v`
Expected: all 4 tests PASS

- [ ] **Step 3: Visually inspect screenshots**

Open each SVG in a browser and verify:
- `limits_oauth.svg`: 3 QuotaCards with percentages, sessions table, plan label
- `limits_hook.svg`: Gauge bars with `~` prefix on percentages
- `limits_no_data.svg`: Setup instructions message
- `session_detail_plan_usage.svg`: PLAN USAGE line with mini bars

- [ ] **Step 4: Run complete test suite**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: all tests PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add tests/test_limits_tab.py
git commit -m "test: add full integration tests with visual validation for Limits feature"
```

---

### Task 12: Fix Regressions and Final Polish

**Files:**
- Modify: `tests/test_dashboard.py` (update counts in existing tests)
- Modify: `claude_spend/dashboard.py` (any CSS tweaks from visual review)

- [ ] **Step 1: Update test counts for new tab**

The new "Limits" tab adds widgets that may change assertion counts. Run:

```bash
python3 -m pytest tests/test_dashboard.py -v --tb=short 2>&1 | grep FAIL
```

For each failing assertion:
- `test_app_mounts_with_data`: Update BigNumber count if quota gauges added different widgets
- `test_table_help_widgets_exist`: Update `.table-help` count (Limits tab adds 1 more)
- `test_tab_switching`: Add "Limits" to the tab switching loop

Example fix for `test_tab_switching`:

```python
for tab_name in ["Sessions", "Limits", "Projects", "Models", "Subagents", "Skills", "Overview"]:
```

Example fix for `test_table_help_widgets_exist`:

```python
assert len(help_widgets) >= 7  # was 6, now includes Limits tab help
```

- [ ] **Step 2: Run full suite and fix until green**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: Visual check — screenshot all tabs**

```python
@pytest.mark.asyncio
async def test_all_tabs_screenshot(tmp_path):
    """Screenshot every tab for visual review."""
    from claude_spend.dashboard import SpendApp
    from claude_spend.quota import QuotaState, DataSource
    from claude_spend.plan_config import PLAN_BUDGETS

    data = _make_test_data()
    quota = QuotaState(
        source=DataSource.HOOK, session_pct=0.65, weekly_pct=0.35,
        estimated_5h_cost=5.72, estimated_weekly_cost=35.0,
        budget=PLAN_BUDGETS["max5"],
    )
    app = SpendApp(data, "Last 7 days", quota_state=quota)
    async with app.run_test(size=(140, 50)) as pilot:
        for tab_name in ["Overview", "Limits", "Sessions"]:
            tabs = app.query("Tab")
            for tab in tabs:
                if tab_name in str(tab.label):
                    await pilot.click(type(tab), offset=(2, 0))
                    break
            await pilot.pause()
            app.save_screenshot(str(tmp_path / f"final_{tab_name.lower()}.svg"))
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "fix: update test assertions for Limits tab, final polish"
```

---

## Summary

| Task | What it builds | Files | Tests |
|-|-|-|-|
| 1 | Plan budget constants + config | `plan_config.py` | 10 |
| 2 | Hook data layer + rolling windows + main() | `hook.py` | 14 |
| 3 | OAuth API client + caching | `usage_api.py` | 9 |
| 4 | Unified QuotaState merger | `quota.py` | 4 |
| 5 | Hook install/uninstall CLI | `hook_install.py` | 8 |
| 6 | QuotaGauge + QuotaCard widgets | `dashboard.py` | 5 |
| 7 | Overview tab quota row | `dashboard.py` | 3 |
| 8 | Limits tab full layout | `dashboard.py` | 4 |
| 9 | Session detail PLAN USAGE | `dashboard.py` | 1 |
| 10 | Wire into main() | `dashboard.py` | 1 |
| 11 | Integration visual validation | `test_limits_tab.py` | 4 |
| 12 | Fix regressions + polish | various | varies |

**Total new tests: ~63**
**Total commits: 12**
