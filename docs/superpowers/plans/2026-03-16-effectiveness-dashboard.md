# Effectiveness Dashboard Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Effectiveness tab and enrichment columns to the existing dashboard, powered by facets + extended session-meta data from `~/.claude/usage-data/`.

**Architecture:** Layered data (Approach C). New `effectiveness.py` module loads facets independently. Existing JSONL pipeline untouched. `SessionMeta` extended with additional fields. `DashboardData` gains effectiveness aggregates. New tab + enriched existing tabs.

**Tech Stack:** Python 3.12, dataclasses, Textual TUI, textual-plotext, pytest

**Spec:** `docs/plans/2026-03-16-effectiveness-dashboard-design.md`

---

## File Structure

| Action | File | Responsibility |
|-|-|-|
| Create | `claude_spend/effectiveness.py` | SessionFacet, SessionEffectiveness, proxy heuristic, facet loader, aggregation |
| Modify | `claude_spend/data.py:57-66` | Extend SessionMeta with new fields |
| Modify | `claude_spend/data.py:79-114` | Load new fields in load_session_metas() |
| Modify | `claude_spend/data.py:441-453` | Add effectiveness fields to DashboardData |
| Modify | `claude_spend/data.py:470-591` | Call effectiveness loader from load_all() |
| Modify | `claude_spend/dashboard.py:261` | Add Effectiveness tab to TabbedContent |
| Modify | `claude_spend/dashboard.py:348-379` | Wire up new tab population |
| Modify | `claude_spend/dashboard.py:398-414` | Add outcome/friction columns to sessions table |
| Modify | `claude_spend/dashboard.py:496-509` | Add avg outcome column to subagents table |
| Modify | `claude_spend/dashboard.py:560-576` | Add avg outcome column to skills table |
| Modify | `claude_spend/dashboard.py:263-267` | Add achievement rate to overview header |
| Modify | `claude_spend/dashboard.py:127-149` | Add _NUMERIC_COLUMNS entries for new columns |
| Create | `tests/test_effectiveness.py` | Tests for facet loading, proxy heuristic, aggregation |

---

## Chunk 1: Data Layer

### Task 1: Extend SessionMeta with new fields

**Files:**
- Modify: `claude_spend/data.py:57-66` (SessionMeta dataclass)
- Modify: `claude_spend/data.py:79-114` (load_session_metas)
- Test: `tests/test_data_models.py`

- [ ] **Step 1: Write failing test for extended SessionMeta loading**

In `tests/test_data_models.py`, add a test that expects the new fields:

```python
def test_session_meta_extended_fields(tmp_claude_dir, sample_session_meta):
    """Extended session-meta fields are loaded."""
    sample_session_meta.update({
        "user_interruptions": 3,
        "tool_errors": 2,
        "tool_error_categories": {"User Rejected": 1, "Other": 1},
        "git_commits": 5,
        "git_pushes": 1,
        "lines_added": 200,
        "lines_removed": 50,
        "files_modified": 4,
        "uses_task_agent": True,
        "uses_mcp": False,
        "uses_web_search": True,
        "user_message_count": 10,
        "assistant_message_count": 20,
    })
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    from claude_spend.data import load_session_metas
    metas = load_session_metas(str(tmp_claude_dir))
    m = metas[0]
    assert m.user_interruptions == 3
    assert m.tool_errors == 2
    assert m.tool_error_categories == {"User Rejected": 1, "Other": 1}
    assert m.git_commits == 5
    assert m.lines_added == 200
    assert m.lines_removed == 50
    assert m.files_modified == 4
    assert m.uses_task_agent is True
    assert m.user_message_count == 10
    assert m.assistant_message_count == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_models.py::test_session_meta_extended_fields -v`
Expected: FAIL with `AttributeError: 'SessionMeta' object has no attribute 'user_interruptions'`

- [ ] **Step 3: Add fields to SessionMeta dataclass**

In `claude_spend/data.py`, extend the `SessionMeta` dataclass (after line 66):

```python
@dataclass
class SessionMeta:
    session_id: str = ""
    project_path: str = ""
    project_name: str = ""
    start_time: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    duration_minutes: int = 0
    first_prompt: str = ""
    tool_counts: dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    # Extended fields for effectiveness tracking
    user_interruptions: int = 0
    tool_errors: int = 0
    tool_error_categories: dict[str, int] = field(default_factory=dict)
    git_commits: int = 0
    git_pushes: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    files_modified: int = 0
    uses_task_agent: bool = False
    uses_mcp: bool = False
    uses_web_search: bool = False
    user_message_count: int = 0
    assistant_message_count: int = 0
```

- [ ] **Step 4: Load new fields in load_session_metas()**

In `load_session_metas()`, update the `SessionMeta(...)` constructor (around line 101) to include:

```python
        results.append(SessionMeta(
            session_id=raw["session_id"],
            project_path=raw.get("project_path", ""),
            project_name=_project_name_from_path(raw.get("project_path", "")),
            start_time=start_time,
            duration_minutes=raw.get("duration_minutes", 0),
            first_prompt=raw.get("first_prompt", ""),
            tool_counts=raw.get("tool_counts", {}),
            input_tokens=raw.get("input_tokens", 0),
            output_tokens=raw.get("output_tokens", 0),
            user_interruptions=raw.get("user_interruptions", 0),
            tool_errors=raw.get("tool_errors", 0),
            tool_error_categories=raw.get("tool_error_categories", {}),
            git_commits=raw.get("git_commits", 0),
            git_pushes=raw.get("git_pushes", 0),
            lines_added=raw.get("lines_added", 0),
            lines_removed=raw.get("lines_removed", 0),
            files_modified=raw.get("files_modified", 0),
            uses_task_agent=raw.get("uses_task_agent", False),
            uses_mcp=raw.get("uses_mcp", False),
            uses_web_search=raw.get("uses_web_search", False),
            user_message_count=raw.get("user_message_count", 0),
            assistant_message_count=raw.get("assistant_message_count", 0),
        ))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_data_models.py::test_session_meta_extended_fields -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -v`
Expected: All existing tests still pass (new fields have defaults so nothing breaks)

- [ ] **Step 7: Commit**

```bash
git add claude_spend/data.py tests/test_data_models.py
git commit -m "feat: extend SessionMeta with effectiveness fields"
```

---

### Task 2: Create effectiveness.py — SessionFacet and loader

**Files:**
- Create: `claude_spend/effectiveness.py`
- Create: `tests/test_effectiveness.py`

- [ ] **Step 1: Write failing test for load_facets**

Create `tests/test_effectiveness.py`:

```python
import json
import os
import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture
def sample_facet():
    return {
        "session_id": "abc-123",
        "underlying_goal": "Fix authentication bug",
        "goal_categories": {"debugging_investigation": 1, "implementation": 1},
        "outcome": "fully_achieved",
        "session_type": "iterative_refinement",
        "claude_helpfulness": "very_helpful",
        "friction_counts": {"tool_permission_error": 1},
        "friction_detail": "User had to approve tool access",
        "primary_success": "multi_file_changes",
        "brief_summary": "Fixed auth bug across multiple files",
    }


def test_load_facets(tmp_claude_dir, sample_facet):
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "abc-123.json", "w") as f:
        json.dump(sample_facet, f)

    from claude_spend.effectiveness import load_facets
    result = load_facets(str(tmp_claude_dir))
    assert "abc-123" in result
    facet = result["abc-123"]
    assert facet.outcome == "fully_achieved"
    assert facet.goal_categories == {"debugging_investigation": 1, "implementation": 1}
    assert facet.friction_counts == {"tool_permission_error": 1}
    assert facet.brief_summary == "Fixed auth bug across multiple files"


def test_load_facets_missing_dir(tmp_claude_dir):
    from claude_spend.effectiveness import load_facets
    result = load_facets(str(tmp_claude_dir))
    assert result == {}


def test_load_facets_invalid_json(tmp_claude_dir):
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "bad.json", "w") as f:
        f.write("not json")

    from claude_spend.effectiveness import load_facets
    result = load_facets(str(tmp_claude_dir))
    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_effectiveness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_spend.effectiveness'`

- [ ] **Step 3: Implement SessionFacet and load_facets**

Create `claude_spend/effectiveness.py`:

```python
"""Effectiveness data: facet loading, proxy heuristic, and aggregation."""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field


@dataclass
class SessionFacet:
    session_id: str = ""
    underlying_goal: str = ""
    goal_categories: dict[str, int] = field(default_factory=dict)
    outcome: str = ""
    session_type: str = ""
    claude_helpfulness: str = ""
    friction_counts: dict[str, int] = field(default_factory=dict)
    friction_detail: str = ""
    primary_success: str = ""
    brief_summary: str = ""


def load_facets(claude_dir: str) -> dict[str, SessionFacet]:
    """Load facet files from usage-data/facets/. Returns dict keyed by session_id."""
    facets_dir = os.path.join(claude_dir, "usage-data", "facets")
    if not os.path.isdir(facets_dir):
        return {}

    result: dict[str, SessionFacet] = {}
    for path in glob.glob(os.path.join(facets_dir, "*.json")):
        try:
            with open(path) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        sid = raw.get("session_id", "")
        if not sid:
            sid = os.path.basename(path).removesuffix(".json")

        result[sid] = SessionFacet(
            session_id=sid,
            underlying_goal=raw.get("underlying_goal", ""),
            goal_categories=raw.get("goal_categories", {}),
            outcome=raw.get("outcome", ""),
            session_type=raw.get("session_type", ""),
            claude_helpfulness=raw.get("claude_helpfulness", ""),
            friction_counts=raw.get("friction_counts", {}),
            friction_detail=raw.get("friction_detail", ""),
            primary_success=raw.get("primary_success", ""),
            brief_summary=raw.get("brief_summary", ""),
        )

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_effectiveness.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add claude_spend/effectiveness.py tests/test_effectiveness.py
git commit -m "feat: add SessionFacet dataclass and facet loader"
```

---

### Task 3: Proxy heuristic and SessionEffectiveness

**Files:**
- Modify: `claude_spend/effectiveness.py`
- Modify: `tests/test_effectiveness.py`

- [ ] **Step 1: Write failing tests for proxy heuristic**

Add to `tests/test_effectiveness.py`:

```python
def test_proxy_score_high(tmp_claude_dir):
    """Session with commits, no errors, no interruptions -> likely_achieved."""
    from claude_spend.data import SessionMeta, SessionSummary
    from claude_spend.effectiveness import compute_proxy_outcome

    meta = SessionMeta(
        session_id="s1",
        git_commits=3,
        tool_errors=0,
        user_interruptions=0,
        duration_minutes=20,
    )
    result = compute_proxy_outcome(meta, median_duration=30)
    assert result == "likely_achieved"


def test_proxy_score_low(tmp_claude_dir):
    """Session with no commits, errors, interruptions -> likely_not_achieved."""
    from claude_spend.data import SessionMeta
    from claude_spend.effectiveness import compute_proxy_outcome

    meta = SessionMeta(
        session_id="s2",
        git_commits=0,
        tool_errors=5,
        user_interruptions=3,
        duration_minutes=90,
    )
    result = compute_proxy_outcome(meta, median_duration=30)
    assert result == "likely_not_achieved"


def test_proxy_score_mid(tmp_claude_dir):
    """Session with commits but also errors -> unclear."""
    from claude_spend.data import SessionMeta
    from claude_spend.effectiveness import compute_proxy_outcome

    meta = SessionMeta(
        session_id="s3",
        git_commits=1,
        tool_errors=8,
        user_interruptions=0,
        duration_minutes=20,
        tool_counts={"Bash": 10, "Read": 5},
    )
    result = compute_proxy_outcome(meta, median_duration=30)
    assert result == "unclear"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_effectiveness.py::test_proxy_score_high tests/test_effectiveness.py::test_proxy_score_low tests/test_effectiveness.py::test_proxy_score_mid -v`
Expected: FAIL with `ImportError: cannot import name 'compute_proxy_outcome'`

- [ ] **Step 3: Implement compute_proxy_outcome**

Add to `claude_spend/effectiveness.py`:

```python
from claude_spend.data import SessionMeta


def compute_proxy_outcome(meta: SessionMeta, median_duration: int) -> str:
    """Estimate session outcome from quantitative signals when no facet exists.

    Scoring:
      +2 if has git commits
      +2 if tool error rate < 10%
      +1 if no user interruptions
      +1 if duration < 2x median

    Returns: "likely_achieved" (>=4), "unclear" (2-3), "likely_not_achieved" (<2)
    """
    score = 0

    if meta.git_commits > 0:
        score += 2

    total_tool_uses = sum(meta.tool_counts.values()) if meta.tool_counts else 0
    error_rate = meta.tool_errors / max(1, total_tool_uses)
    if error_rate < 0.10:
        score += 2

    if meta.user_interruptions == 0:
        score += 1

    if median_duration > 0 and meta.duration_minutes < 2 * median_duration:
        score += 1

    if score >= 4:
        return "likely_achieved"
    elif score >= 2:
        return "unclear"
    else:
        return "likely_not_achieved"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_effectiveness.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Write failing test for SessionEffectiveness builder**

Add to `tests/test_effectiveness.py`:

```python
def test_build_effectiveness_with_facet():
    from claude_spend.data import SessionMeta, SessionSummary, TokenUsage
    from claude_spend.effectiveness import SessionFacet, build_session_effectiveness

    facet = SessionFacet(
        session_id="s1",
        outcome="fully_achieved",
        goal_categories={"implementation": 1},
        friction_counts={"tool_permission_error": 2},
    )
    session = SessionSummary(
        session_id="s1",
        estimated_cost=3.50,
    )
    meta = SessionMeta(session_id="s1")

    result = build_session_effectiveness(
        session=session, meta=meta, facet=facet, category_avg_costs={"implementation": 4.00},
    )
    assert result.outcome == "fully_achieved"
    assert result.outcome_source == "facet"
    assert result.efficiency_score == pytest.approx(3.50 / 4.00)
    assert result.friction_counts == {"tool_permission_error": 2}


def test_build_effectiveness_without_facet():
    from claude_spend.data import SessionMeta, SessionSummary
    from claude_spend.effectiveness import build_session_effectiveness

    session = SessionSummary(session_id="s2", estimated_cost=2.00)
    meta = SessionMeta(session_id="s2", git_commits=2, tool_errors=0, user_interruptions=0, duration_minutes=15)

    result = build_session_effectiveness(
        session=session, meta=meta, facet=None,
        category_avg_costs={}, median_duration=30,
    )
    assert result.outcome == "likely_achieved"
    assert result.outcome_source == "proxy"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_effectiveness.py::test_build_effectiveness_with_facet -v`
Expected: FAIL with `ImportError: cannot import name 'build_session_effectiveness'`

- [ ] **Step 7: Implement SessionEffectiveness and builder**

Add to `claude_spend/effectiveness.py`:

```python
import statistics
from claude_spend.data import SessionSummary


@dataclass
class SessionEffectiveness:
    session_id: str = ""
    outcome: str = ""
    outcome_source: str = ""  # "facet" or "proxy"
    goal_categories: dict[str, int] = field(default_factory=dict)
    efficiency_score: float = 0.0
    friction_counts: dict[str, int] = field(default_factory=dict)


ACHIEVED_OUTCOMES = {"fully_achieved", "mostly_achieved", "likely_achieved"}


def build_session_effectiveness(
    session: SessionSummary,
    meta: SessionMeta,
    facet: SessionFacet | None,
    category_avg_costs: dict[str, float],
    median_duration: int = 30,
) -> SessionEffectiveness:
    """Build effectiveness record for a single session."""
    if facet and facet.outcome:
        outcome = facet.outcome
        source = "facet"
        categories = facet.goal_categories
        friction = facet.friction_counts
    else:
        outcome = compute_proxy_outcome(meta, median_duration)
        source = "proxy"
        categories = {}
        friction = {}

    # Efficiency score: session cost / avg cost for its primary category
    primary_cat = max(categories, key=categories.get) if categories else None
    if primary_cat and primary_cat in category_avg_costs and category_avg_costs[primary_cat] > 0:
        efficiency = session.estimated_cost / category_avg_costs[primary_cat]
    else:
        efficiency = 0.0

    return SessionEffectiveness(
        session_id=session.session_id,
        outcome=outcome,
        outcome_source=source,
        goal_categories=categories,
        efficiency_score=efficiency,
        friction_counts=friction,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_effectiveness.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 9: Commit**

```bash
git add claude_spend/effectiveness.py tests/test_effectiveness.py
git commit -m "feat: add proxy heuristic and SessionEffectiveness builder"
```

---

### Task 4: Effectiveness aggregation functions

**Files:**
- Modify: `claude_spend/effectiveness.py`
- Modify: `tests/test_effectiveness.py`

- [ ] **Step 1: Write failing test for aggregate_effectiveness**

Add to `tests/test_effectiveness.py`:

```python
def test_aggregate_effectiveness():
    from claude_spend.data import SessionSummary, SessionMeta
    from claude_spend.effectiveness import (
        SessionEffectiveness, EffectivenessAggregates, aggregate_effectiveness,
    )

    records = [
        SessionEffectiveness(session_id="s1", outcome="fully_achieved", outcome_source="facet",
                             goal_categories={"implementation": 1}, efficiency_score=0.8,
                             friction_counts={"tool_permission_error": 1}),
        SessionEffectiveness(session_id="s2", outcome="mostly_achieved", outcome_source="proxy",
                             goal_categories={"debugging": 1}, efficiency_score=1.2,
                             friction_counts={}),
        SessionEffectiveness(session_id="s3", outcome="not_achieved", outcome_source="facet",
                             goal_categories={"implementation": 1}, efficiency_score=2.0,
                             friction_counts={"wrong_approach": 1, "tool_permission_error": 1}),
    ]
    sessions_by_id = {
        "s1": SessionSummary(session_id="s1", estimated_cost=3.00, duration_minutes=20),
        "s2": SessionSummary(session_id="s2", estimated_cost=2.00, duration_minutes=15),
        "s3": SessionSummary(session_id="s3", estimated_cost=7.00, duration_minutes=40),
    }
    metas_by_id = {
        "s1": SessionMeta(session_id="s1", duration_minutes=20),
        "s2": SessionMeta(session_id="s2", duration_minutes=15),
        "s3": SessionMeta(session_id="s3", duration_minutes=40),
    }

    agg = aggregate_effectiveness(records, sessions_by_id, metas_by_id)
    assert agg.total_sessions == 3
    assert agg.faceted_count == 2
    assert agg.proxied_count == 1
    # 2 of 3 are achieved (fully + mostly)
    assert agg.achievement_rate == pytest.approx(2 / 3)
    assert agg.avg_efficiency == pytest.approx((0.8 + 1.2 + 2.0) / 3)
    # friction: tool_permission_error=2, wrong_approach=1
    assert agg.friction_totals["tool_permission_error"] == 2
    assert agg.friction_totals["wrong_approach"] == 1
    # friction avg extra cost should be populated
    assert "tool_permission_error" in agg.friction_avg_extra_cost
    # category breakdown
    assert "implementation" in agg.category_stats
    assert agg.category_stats["implementation"]["sessions"] == 2
    assert agg.category_stats["implementation"]["achievement_rate"] == pytest.approx(0.5)
    assert agg.category_stats["implementation"]["avg_cost"] == pytest.approx(5.0)
    assert agg.category_stats["implementation"]["avg_duration"] == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_effectiveness.py::test_aggregate_effectiveness -v`
Expected: FAIL with `ImportError: cannot import name 'EffectivenessAggregates'`

- [ ] **Step 3: Implement EffectivenessAggregates and aggregate_effectiveness**

Add to `claude_spend/effectiveness.py`:

```python
@dataclass
class CategoryStats:
    sessions: int = 0
    avg_cost: float = 0.0
    avg_duration: int = 0
    achievement_rate: float = 0.0
    avg_efficiency: float = 0.0


@dataclass
class EffectivenessAggregates:
    total_sessions: int = 0
    faceted_count: int = 0
    proxied_count: int = 0
    achievement_rate: float = 0.0
    avg_friction: float = 0.0
    avg_efficiency: float = 0.0
    friction_totals: dict[str, int] = field(default_factory=dict)
    friction_avg_extra_cost: dict[str, float] = field(default_factory=dict)
    category_stats: dict[str, dict] = field(default_factory=dict)


def aggregate_effectiveness(
    records: list[SessionEffectiveness],
    sessions_by_id: dict[str, SessionSummary] | None = None,
    metas_by_id: dict[str, SessionMeta] | None = None,
) -> EffectivenessAggregates:
    """Compute aggregate effectiveness metrics from per-session records."""
    if not records:
        return EffectivenessAggregates()

    sessions_by_id = sessions_by_id or {}
    metas_by_id = metas_by_id or {}

    faceted = [r for r in records if r.outcome_source == "facet"]
    proxied = [r for r in records if r.outcome_source == "proxy"]
    achieved = [r for r in records if r.outcome in ACHIEVED_OUTCOMES]

    # Overall avg cost (for friction extra-cost calculation)
    all_costs = [sessions_by_id[r.session_id].estimated_cost for r in records if r.session_id in sessions_by_id]
    overall_avg_cost = sum(all_costs) / len(all_costs) if all_costs else 0.0

    # Friction totals + avg extra cost per friction type
    friction_totals: dict[str, int] = {}
    friction_session_costs: dict[str, list[float]] = {}
    for r in records:
        for k, v in r.friction_counts.items():
            friction_totals[k] = friction_totals.get(k, 0) + v
            cost = sessions_by_id.get(r.session_id)
            if cost:
                friction_session_costs.setdefault(k, []).append(cost.estimated_cost)

    friction_avg_extra_cost: dict[str, float] = {}
    for ftype, costs in friction_session_costs.items():
        avg_friction_cost = sum(costs) / len(costs)
        friction_avg_extra_cost[ftype] = max(0, avg_friction_cost - overall_avg_cost)

    total_friction = sum(friction_totals.values())
    efficiency_scores = [r.efficiency_score for r in records if r.efficiency_score > 0]

    # Category breakdown
    by_cat: dict[str, list[SessionEffectiveness]] = {}
    for r in records:
        for cat in r.goal_categories:
            by_cat.setdefault(cat, []).append(r)

    category_stats: dict[str, dict] = {}
    for cat, cat_records in by_cat.items():
        cat_achieved = [r for r in cat_records if r.outcome in ACHIEVED_OUTCOMES]
        cat_eff = [r.efficiency_score for r in cat_records if r.efficiency_score > 0]
        cat_costs = [sessions_by_id[r.session_id].estimated_cost for r in cat_records if r.session_id in sessions_by_id]
        cat_durs = [metas_by_id[r.session_id].duration_minutes for r in cat_records if r.session_id in metas_by_id]
        category_stats[cat] = {
            "sessions": len(cat_records),
            "avg_cost": sum(cat_costs) / len(cat_costs) if cat_costs else 0.0,
            "avg_duration": sum(cat_durs) // len(cat_durs) if cat_durs else 0,
            "achievement_rate": len(cat_achieved) / len(cat_records),
            "avg_efficiency": sum(cat_eff) / len(cat_eff) if cat_eff else 0.0,
        }

    return EffectivenessAggregates(
        total_sessions=len(records),
        faceted_count=len(faceted),
        proxied_count=len(proxied),
        achievement_rate=len(achieved) / len(records),
        avg_friction=total_friction / len(records),
        avg_efficiency=sum(efficiency_scores) / len(efficiency_scores) if efficiency_scores else 0.0,
        friction_totals=friction_totals,
        friction_avg_extra_cost=friction_avg_extra_cost,
        category_stats=category_stats,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_effectiveness.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Commit**

```bash
git add claude_spend/effectiveness.py tests/test_effectiveness.py
git commit -m "feat: add effectiveness aggregation"
```

---

### Task 5: Wire effectiveness into DashboardData and load_all()

**Files:**
- Modify: `claude_spend/data.py:441-453` (DashboardData)
- Modify: `claude_spend/data.py:470-591` (load_all)
- Modify: `tests/test_effectiveness.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_effectiveness.py`:

```python
def test_load_all_includes_effectiveness(tmp_claude_dir, sample_session_meta, sample_facet):
    """load_all() populates effectiveness data when facets exist."""
    # Write session-meta
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # Write facet
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "abc-123.json", "w") as f:
        json.dump(sample_facet, f)

    from claude_spend.data import load_all
    data = load_all(str(tmp_claude_dir))
    assert data.facets_loaded == 1
    assert len(data.effectiveness) == 1
    assert data.effectiveness[0].outcome == "fully_achieved"
    assert data.effectiveness[0].outcome_source == "facet"


def test_load_all_no_facets(tmp_claude_dir, sample_session_meta):
    """load_all() uses proxy when no facets exist."""
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    sample_session_meta.update({"git_commits": 3, "tool_errors": 0, "user_interruptions": 0})
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    from claude_spend.data import load_all
    data = load_all(str(tmp_claude_dir))
    assert data.facets_loaded == 0
    assert data.proxied_count == 1
    assert len(data.effectiveness) == 1
    assert data.effectiveness[0].outcome_source == "proxy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_effectiveness.py::test_load_all_includes_effectiveness -v`
Expected: FAIL with `AttributeError: 'DashboardData' object has no attribute 'facets_loaded'`

- [ ] **Step 3: Add effectiveness fields to DashboardData**

In `claude_spend/data.py`, add to the `DashboardData` dataclass (after `parse_errors`):

```python
    # Effectiveness layer (use TYPE_CHECKING to avoid circular import)
    effectiveness: list[SessionEffectiveness] = field(default_factory=list)
    effectiveness_agg: EffectivenessAggregates | None = None
    facets_loaded: int = 0
    proxied_count: int = 0
```

At the top of `data.py`, add a TYPE_CHECKING guard (after existing imports):

```python
from __future__ import annotations  # already present
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_spend.effectiveness import SessionEffectiveness, EffectivenessAggregates
```

Since `from __future__ import annotations` is already present, all annotations are strings at runtime — no circular import.

- [ ] **Step 4: Wire effectiveness loading into load_all()**

At the end of `load_all()` in `claude_spend/data.py`, before the `return DashboardData(...)`, add:

```python
    # Effectiveness layer
    from claude_spend.effectiveness import (
        load_facets, build_session_effectiveness, aggregate_effectiveness,
    )
    facets = load_facets(claude_dir)

    # Build meta lookup for proxy heuristic
    meta_by_id = {m.session_id: m for m in metas}
    durations = [m.duration_minutes for m in metas if m.duration_minutes > 0]
    median_dur = statistics.median(durations) if durations else 30

    # First pass: compute category avg costs from faceted sessions
    cat_costs: dict[str, list[float]] = {}
    for s in sessions:
        f = facets.get(s.session_id)
        if f and f.goal_categories:
            for cat in f.goal_categories:
                cat_costs.setdefault(cat, []).append(s.estimated_cost)
    category_avg_costs = {cat: sum(costs) / len(costs) for cat, costs in cat_costs.items()}

    # Second pass: build effectiveness records
    effectiveness_records = []
    for s in sessions:
        meta = meta_by_id.get(s.session_id)
        if not meta:
            continue
        eff = build_session_effectiveness(
            session=s, meta=meta, facet=facets.get(s.session_id),
            category_avg_costs=category_avg_costs, median_duration=int(median_dur),
        )
        effectiveness_records.append(eff)

    sessions_by_id = {s.session_id: s for s in sessions}
    eff_agg = aggregate_effectiveness(effectiveness_records, sessions_by_id, meta_by_id)
```

Then update the `return DashboardData(...)` to include:

```python
        effectiveness=effectiveness_records,
        effectiveness_agg=eff_agg,
        facets_loaded=len(facets),
        proxied_count=eff_agg.proxied_count,
```

Also add `import statistics` at the top of `data.py` (it is NOT currently imported there — `dashboard.py` imports it but `data.py` does not).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_effectiveness.py -v`
Expected: PASS (all 11 tests)

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add claude_spend/data.py tests/test_effectiveness.py
git commit -m "feat: wire effectiveness layer into load_all()"
```

---

## Chunk 2: Dashboard UI

### Task 6: Add Effectiveness tab to dashboard

**Files:**
- Modify: `claude_spend/dashboard.py:261` (TabbedContent)
- Modify: `claude_spend/dashboard.py` (new compose widgets + populate methods)

- [ ] **Step 1: Add Effectiveness tab to TabbedContent**

In `dashboard.py`, update the `TabbedContent` line (261) to include "Effectiveness" as the second tab:

```python
        with TabbedContent("Overview", "Effectiveness", "Sessions", "Projects", "Models", "Subagents", "Skills"):
```

- [ ] **Step 2: Add TabPane for Effectiveness between Overview and Sessions**

After the Overview TabPane closing, add:

```python
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
                    yield Static("[#666666]Efficiency = category avg cost / overall avg cost[/#666666]", classes="table-help")
                    yield DataTable(id="category-table")
                else:
                    yield Static(
                        "[dim]No effectiveness data available. Run /insights to generate session facets.[/dim]",
                        id="no-effectiveness",
                    )
```

- [ ] **Step 3: Add CSS for effectiveness tab**

In the CSS string, add:

```css
    #effectiveness-numbers {
        height: auto;
        padding: 0 1;
    }
```

- [ ] **Step 4: Add populate methods for friction and category tables**

Add new methods to SpendApp:

```python
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
```

- [ ] **Step 5: Wire populate calls in on_mount and on_tab_activated**

In `on_mount()`, add after existing populate calls:

```python
            self._populate_friction_table()
            self._populate_category_table()
```

No lazy-load needed for these (no charts, just tables — same as other tabs).

- [ ] **Step 6: Run the app manually to verify**

Run: `python -m claude_spend.dashboard`
Expected: Effectiveness tab appears second. Shows stats bar, friction table, category table. If no facets, shows fallback message.

- [ ] **Step 7: Commit**

```bash
git add claude_spend/dashboard.py
git commit -m "feat: add Effectiveness tab with friction and category tables"
```

---

### Task 7: Enrich Sessions table with outcome and friction columns

**Files:**
- Modify: `claude_spend/dashboard.py` (_populate_sessions_table)

- [ ] **Step 1: Build effectiveness lookup helper**

Add a helper method to SpendApp:

```python
    def _eff_lookup(self) -> dict[str, object]:
        """Build session_id -> SessionEffectiveness lookup."""
        return {e.session_id: e for e in self.data.effectiveness}
```

- [ ] **Step 2: Update sessions table columns and rows**

In `_populate_sessions_table`, update `add_columns` to include Outcome and Friction:

```python
        table.add_columns("Date", "Project", "First Prompt", "Duration", "Tokens", "Cost", "Skills", "Cache%", "Outcome", "Friction")
```

And update the `add_row` call to include the new values:

```python
        eff_map = self._eff_lookup()
        for i, s in enumerate(self._sessions_ordered):
            eff = eff_map.get(s.session_id)
            outcome_text = self._fmt_outcome(eff) if eff else Text("—", style="dim")
            friction_text = self._fmt_friction_count(eff) if eff else Text("")
            table.add_row(
                s.start_time.strftime("%Y-%m-%d %H:%M"),
                s.project_name[:25],
                s.first_prompt[:40],
                _fmt_duration(s.duration_minutes),
                _fmt_tokens(s.total_usage.total),
                _fmt_cost(s.estimated_cost),
                str(len(s.skill_invocations)),
                _fmt_cache_pct(s.cache_hit_ratio),
                outcome_text,
                friction_text,
                key=str(i),
            )
```

- [ ] **Step 3: Add formatting helpers**

```python
    @staticmethod
    def _fmt_outcome(eff) -> Text:
        outcome_colors = {
            "fully_achieved": ("fully", "green"),
            "mostly_achieved": ("mostly", "yellow"),
            "partially_achieved": ("partial", "dark_orange"),
            "not_achieved": ("not", "red"),
            "likely_achieved": ("~likely", "dim green"),
            "unclear": ("~unclear", "dim"),
            "likely_not_achieved": ("~not", "dim red"),
        }
        label, color = outcome_colors.get(eff.outcome, (eff.outcome, "dim"))
        return Text(label, style=color)

    @staticmethod
    def _fmt_friction_count(eff) -> Text:
        total = sum(eff.friction_counts.values()) if eff.friction_counts else 0
        if total == 0:
            return Text("")
        color = "dark_orange" if total <= 2 else "red"
        return Text(str(total), style=color)
```

- [ ] **Step 4: Run the app manually to verify**

Run: `python -m claude_spend.dashboard`
Expected: Sessions table shows Outcome and Friction columns. Faceted sessions show colored labels, proxied show `~` prefix.

- [ ] **Step 5: Commit**

```bash
git add claude_spend/dashboard.py
git commit -m "feat: add outcome and friction columns to sessions table"
```

---

### Task 8: Enrich Subagents, Skills, and Overview tabs

**Files:**
- Modify: `claude_spend/dashboard.py`

- [ ] **Step 1: Add avg outcome column to subagents table**

In `_populate_subagents_table`, update `add_columns`:

```python
        table.add_columns("Type", "Calls", "Avg Tokens", "Total Tokens", "Primary Model", "Cost", "Avg Outcome")
```

Compute achievement rate per subagent type and add to each row:

```python
    def _populate_subagents_table(self) -> None:
        table = self.query_one("#subagents-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Type", "Calls", "Avg Tokens", "Total Tokens", "Primary Model", "Cost", "Avg Outcome")

        # Build subagent_type -> set of session_ids
        from claude_spend.effectiveness import ACHIEVED_OUTCOMES
        type_sessions: dict[str, set[str]] = {}
        for c in self.data.all_subagent_calls:
            type_sessions.setdefault(c.subagent_type, set()).add(c.session_id)

        eff_map = self._eff_lookup()

        for a in self.data.subagent_types:
            primary_model = max(a.models_used, key=a.models_used.get) if a.models_used else "unknown"
            sids = type_sessions.get(a.subagent_type, set())
            effs = [eff_map[sid] for sid in sids if sid in eff_map]
            if effs:
                achieved = sum(1 for e in effs if e.outcome in ACHIEVED_OUTCOMES)
                rate = achieved / len(effs) * 100
                color = "green" if rate >= 70 else "dark_orange" if rate >= 50 else "red"
                outcome_text = Text(f"{rate:.0f}%", style=color)
            else:
                outcome_text = Text("—", style="dim")
            table.add_row(
                a.subagent_type,
                str(a.call_count),
                _fmt_tokens(a.avg_tokens_per_call),
                _fmt_tokens(a.total_usage.total),
                primary_model.split("-")[1] if "-" in primary_model else primary_model,
                _fmt_cost(a.estimated_cost),
                outcome_text,
            )
```

- [ ] **Step 2: Add avg outcome column to skills table**

In `_populate_skills_table`, update `add_columns`:

```python
        table.add_columns("Skill", "Uses", "Avg Cost", "Cost Delta", "Cache Hit", "Cache R:W", "Avg Dur", "Avg Turns", "Avg Outcome")
```

And add the outcome computation:

```python
        from claude_spend.effectiveness import ACHIEVED_OUTCOMES
        eff_map = self._eff_lookup()
        for a in self.data.skill_types:
            effs = [eff_map[sid] for sid in a.session_ids if sid in eff_map]
            if effs:
                achieved = sum(1 for e in effs if e.outcome in ACHIEVED_OUTCOMES)
                rate = achieved / len(effs) * 100
                color = "green" if rate >= 70 else "dark_orange" if rate >= 50 else "red"
                outcome_text = Text(f"{rate:.0f}%", style=color)
            else:
                outcome_text = Text("—", style="dim")
            table.add_row(
                a.skill_name,
                str(a.invocation_count),
                _fmt_cost(a.avg_session_cost),
                _fmt_cost_delta(a.cost_delta),
                _fmt_cache_pct(a.avg_cache_hit_ratio),
                _fmt_cache_rw(a.avg_cache_rw_ratio),
                _fmt_duration(a.avg_duration_minutes),
                str(a.avg_turn_count),
                outcome_text,
            )
```

- [ ] **Step 3: Add achievement rate to Overview header**

In the Overview TabPane's `Horizontal` (id="overview-numbers"), add a fourth BigNumber:

```python
                    eff_agg = self.data.effectiveness_agg
                    if eff_agg and eff_agg.total_sessions > 0:
                        ach_label = f"{eff_agg.achievement_rate * 100:.0f}% ({eff_agg.faceted_count}f)"
                    else:
                        ach_label = "—"
                    yield BigNumber("Achievement", ach_label)
```

- [ ] **Step 4: Add _NUMERIC_COLUMNS entries for new sortable columns**

In `dashboard.py`, add to the `_NUMERIC_COLUMNS` dict (around line 149):

```python
    "Friction": _parse_int_str,
    "Avg Outcome": _parse_pct_str,
    "Achievement Rate": _parse_pct_str,
    "Efficiency": lambda s: float(str(s).replace("x", "").replace("n/a", "0")),
    "% Sessions": _parse_pct_str,
    "Count": _parse_int_str,
    "Avg Extra Cost": lambda s: float(str(s).replace("+", "").replace("$", "")) if str(s).strip() else 0.0,
    "Avg Cost": _parse_cost_str,
    "Avg Duration": _parse_duration_str,
```

- [ ] **Step 5: Run the app manually to verify all enrichments**

Run: `python -m claude_spend.dashboard`
Expected:
- Overview: shows Achievement Rate BigNumber
- Sessions: Outcome and Friction columns populated
- Subagents: Avg Outcome column
- Skills: Avg Outcome column

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add claude_spend/dashboard.py
git commit -m "feat: add effectiveness enrichments to subagents, skills, and overview"
```

---

### Task 9: Final integration test and cleanup

**Files:**
- Modify: `tests/test_effectiveness.py`

- [ ] **Step 1: Add end-to-end test with full fixture**

Add to `tests/test_effectiveness.py`:

```python
def test_effectiveness_end_to_end(tmp_claude_dir, sample_session_meta, sample_facet, sample_jsonl_messages):
    """Full pipeline: meta + facet + JSONL -> effectiveness data on DashboardData."""
    # Write session-meta with extended fields
    sample_session_meta.update({
        "git_commits": 2, "tool_errors": 0, "user_interruptions": 0,
        "lines_added": 100, "files_modified": 3,
    })
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # Write facet
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "abc-123.json", "w") as f:
        json.dump(sample_facet, f)

    # Write JSONL
    project_dir = tmp_claude_dir / "projects" / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)
    with open(project_dir / "abc-123.jsonl", "w") as f:
        for msg in sample_jsonl_messages:
            f.write(json.dumps(msg) + "\n")

    from claude_spend.data import load_all
    data = load_all(str(tmp_claude_dir))

    # Verify existing data still works
    assert len(data.sessions) == 1
    assert data.sessions[0].estimated_cost > 0

    # Verify effectiveness layer
    assert data.facets_loaded == 1
    assert len(data.effectiveness) == 1
    eff = data.effectiveness[0]
    assert eff.outcome == "fully_achieved"
    assert eff.outcome_source == "facet"
    assert eff.goal_categories == {"debugging_investigation": 1, "implementation": 1}

    # Verify aggregates
    assert data.effectiveness_agg is not None
    assert data.effectiveness_agg.achievement_rate == 1.0
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_effectiveness.py::test_effectiveness_end_to_end -v`
Expected: PASS

- [ ] **Step 3: Run full suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_effectiveness.py
git commit -m "test: add end-to-end effectiveness integration test"
```
