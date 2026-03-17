# Effectiveness Dashboard Design

## Problem

The dashboard tracks spending (cost, tokens, models) but not effectiveness. The `~/.claude/usage-data/` directory contains two additional data sources — **facets** (AI-judged session outcomes) and **session-meta** (extended quantitative metrics) — that can answer: "Are we getting value for what we spend?"

## Data Sources

### Facets (`usage-data/facets/*.json`) — ~24% of sessions
AI-generated qualitative analysis per session:
- `outcome`: fully_achieved, mostly_achieved, partially_achieved, not_achieved
- `goal_categories`: {debugging: 1, implementation: 1, design: 1, ...}
- `session_type`: iterative_refinement, single_task, etc.
- `claude_helpfulness`: very_helpful, helpful, etc.
- `friction_counts`: {excessive_process: 1, tool_permission_error: 1, ...}
- `friction_detail`: free text
- `primary_success`: good_explanations, multi_file_changes, etc.
- `brief_summary`: one-line narrative
- `user_satisfaction_counts`: {satisfied: N, likely_satisfied: N, ...}

### Session-Meta (`usage-data/session-meta/*.json`) — all sessions
Extended quantitative metadata (beyond what's currently loaded):
- `user_interruptions`, `tool_errors`, `tool_error_categories`
- `git_commits`, `git_pushes`, `lines_added`, `lines_removed`, `files_modified`
- `uses_task_agent`, `uses_mcp`, `uses_web_search`
- `user_message_count`, `assistant_message_count`

## Architecture: Approach C — Layered Data with Lazy Loading

Keep existing JSONL pipeline untouched. Add a separate effectiveness layer that loads facets + extended session-meta independently. The Effectiveness tab uses this layer directly. Existing tabs pull from it for enrichment columns via session_id lookup.

**Key properties:**
- Consumer only — dashboard reads existing facets, never generates them
- Graceful degradation — no facets = proxy-only mode, no session-meta = effectiveness tab empty, spend tabs work unchanged
- Minimal refactor — new module, extend existing dataclass, add fields to DashboardData

## KPIs Tracked

1. **Cost-effectiveness** — context-aware efficiency score relative to similar sessions (segmented by goal_categories)
2. **Tool utilization** — which tools used most, error rates per tool, tool diversity
3. **Friction tracking** — frequency and types of friction events
4. **Subagent/skill ROI** — achievement rate of sessions using each subagent type or skill
5. **Session efficiency** — tokens per commit, cost per line of code, duration vs output (context-dependent)
6. **Cache hit rate** — correlated with effectiveness metrics

## New Data Model

### New module: `claude_spend/effectiveness.py`

```python
@dataclass
class SessionFacet:
    session_id: str
    underlying_goal: str
    goal_categories: dict[str, int]
    outcome: str                        # fully_achieved, mostly_achieved, etc.
    session_type: str
    claude_helpfulness: str
    friction_counts: dict[str, int]
    friction_detail: str
    primary_success: str
    brief_summary: str

@dataclass
class SessionEffectiveness:
    """Merged view: one per session, combining facet + proxy + cost data."""
    session_id: str
    outcome: str                        # from facet or proxy
    outcome_source: str                 # "facet" or "proxy"
    goal_categories: dict[str, int]
    efficiency_score: float             # cost relative to avg for same category
    friction_counts: dict[str, int]
```

### Proxy Heuristic (when no facet exists)

Score based on session-meta signals:
- Has git commits -> +2
- Tool error rate < 10% -> +2
- User interruptions == 0 -> +1
- Duration < 2x median for category -> +1
- Score >= 4 -> "likely_achieved"
- Score 2-3 -> "unclear"
- Score < 2 -> "likely_not_achieved"

### Extended SessionMeta fields

Add to existing `SessionMeta` dataclass in `data.py`:
```python
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

### New fields on DashboardData

```python
effectiveness: list[SessionEffectiveness] = field(default_factory=list)
facets_loaded: int = 0
proxied_count: int = 0
```

## New Tab: Effectiveness

Position: second tab (after Overview).

### Panel 1 — Outcome Summary (horizontal stats bar)
- Sessions Analyzed: `42 facet / 158 proxy / 200 total`
- Achievement Rate: `78%` (fully + mostly achieved)
- Avg Friction Score: `1.2 per session`
- Avg Efficiency: `0.85x` (< 1.0 = cheaper than category avg = good)

### Panel 2 — Friction Breakdown (DataTable)
Columns: Friction Type | Count | % Sessions | Avg Extra Cost

Ranked by frequency. Shows which friction types are most common and how much they cost.

### Panel 3 — Efficiency by Category (DataTable)
Columns: Category | Sessions | Avg Cost | Avg Duration | Achievement Rate | Efficiency

Efficiency = category avg cost / overall avg cost. Segments by goal_categories from facets.

## Enrichments to Existing Tabs

### Sessions table — 2 new columns
- **Outcome**: colored badge (green=fully, yellow=mostly, orange=partial, red=not). Proxy estimates shown with `~` prefix in dim style.
- **Friction**: count of friction events (0=blank, >0=orange/red number)

### Subagents table — 1 new column
- **Avg Outcome**: achievement rate of sessions using that subagent type

### Skills table — 1 new column
- **Avg Outcome**: achievement rate of sessions using that skill

### Overview header — 1 new stat
- **Achievement Rate**: `78% (42 faceted sessions)`

## Data Flow

1. Load session-metas — existing, extended with new fields
2. Build JSONL index + parse conversations — existing, unchanged
3. **New:** `load_facets(claude_dir, days)` -> `dict[session_id, SessionFacet]`
4. **New:** For each SessionSummary, compute SessionEffectiveness (facet if available, proxy if not)
5. **New:** Aggregate effectiveness by category, compute friction rollups, efficiency scores
6. Store on DashboardData

## Graceful Degradation

- No `usage-data/facets/` -> effectiveness tab shows "No facet data available. Run /insights to generate." Proxy columns show `~` prefix.
- No `usage-data/session-meta/` -> effectiveness layer empty, spend tabs work unchanged.
- Partial data -> mixed facet/proxy sources, clearly labeled per session.

## Context-Aware Cost-Effectiveness

Cost-per-outcome is segmented by goal_categories:
- **Implementation sessions** — cost per commit, cost per line changed
- **Planning/design sessions** — cost vs avg for that category, with outcome
- **Debugging sessions** — cost to resolve vs avg debugging cost
- **Pipeline/generation sessions** — cost per files_modified

Efficiency score = session cost / avg cost for same category. < 1.0 is efficient, > 1.0 is expensive relative to peers.
