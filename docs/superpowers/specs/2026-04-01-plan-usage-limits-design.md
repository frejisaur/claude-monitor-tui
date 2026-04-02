# Plan Usage Limits — Design Spec

**Date:** 2026-04-01
**Status:** Draft

## Overview

Add plan usage limit tracking to claude-spend-tui so users can see how much of their Claude Pro/Max quota they've consumed — per session, per 5-hour window, and per 7-day week — broken down by plan tier.

Two complementary data sources:

1. **OAuth Usage API** — calls Anthropic's undocumented `/api/oauth/usage` endpoint for real-time quota percentages (when OAuth credentials are available)
2. **Stop Hook tracker** — a globally-installed Claude Code hook that logs per-turn token usage to a local store, enabling estimated quota tracking for all users

## Data Layer

### 1. OAuth Usage API (`claude_spend/usage_api.py`)

**Endpoint:** `GET https://api.anthropic.com/api/oauth/usage`

**Auth:** `Authorization: Bearer {token}` from `~/.claude/.credentials.json` at key path `claudeAiOauth.accessToken`. Header `anthropic-beta: oauth-2025-04-20`.

**Response dataclass:**

```python
@dataclass
class QuotaSnapshot:
    session_pct: float          # 0.0–1.0, 5h window utilization
    weekly_pct: float           # 0.0–1.0, 7d all-model utilization
    sonnet_weekly_pct: float    # 0.0–1.0, 7d sonnet-specific utilization
    session_reset_at: datetime  # ISO 8601 reset timestamp
    weekly_reset_at: datetime   # ISO 8601 reset timestamp
    plan_name: str | None       # e.g. "max5", "pro", inferred or configured
```

**Behavior:**
- Cache response to `~/.claude-spend/quota-cache.json` with TTL of 60 seconds
- If credentials file missing, API unreachable, or token expired: return `None`
- Never block the UI — fetch async with `set_interval(60)` refresh

### 2. Stop Hook Tracker (`claude_spend/hook.py`)

**Hook event:** `Stop` (fires after each assistant turn completes)

**Input (from stdin):** JSON with `session_id`, `transcript_path`, `cwd` (per Claude Code hooks spec, `Stop` events include `session_id` and `transcript_path` pointing to the session JSONL file)

**Hook script behavior:**
1. Read `transcript_path` (session JSONL). If `transcript_path` is not provided, resolve from `~/.claude/projects/*/` using `session_id`.
2. Find the most recent assistant message with `usage` data
3. Extract: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `model`
4. Calculate estimated cost using existing `PRICING` constants
5. Append to `~/.claude-spend/usage-log.jsonl`:

```json
{
  "ts": "2026-04-01T14:23:45Z",
  "session_id": "abc-123",
  "model": "claude-opus-4-6",
  "input_tokens": 45000,
  "output_tokens": 1200,
  "cache_write_tokens": 3000,
  "cache_read_tokens": 40000,
  "estimated_cost": 0.42,
  "project": "claude-spend-tui"
}
```

**Deduplication:** Include a hash of `(session_id, message_id)` to prevent duplicate entries if the hook fires multiple times for the same turn.

**Rolling window computation:**
- 5h window: sum all entries with `ts` within last 5 hours
- 7d window: sum all entries with `ts` within last 7 days
- Per-session contribution: session cost / window total cost * window quota percentage

### 3. Plan Configuration (`~/.claude-spend/config.json`)

```json
{
  "plan": "max5",
  "custom_budgets": null
}
```

**Built-in plan budgets (approximate, from community research):**

| Plan | 5h Window (est.) | Weekly (est.) | Price |
|-|-|-|-|
| `pro` | ~$4.40 | ~$20 | $20/mo |
| `max5` | ~$8.80 | ~$100 | $100/mo |
| `max20` | ~$22.00 | ~$200 | $200/mo |

These are rough estimates. Users can override with `custom_budgets`:
```json
{
  "plan": "custom",
  "custom_budgets": {
    "5h_budget": 10.0,
    "weekly_budget": 150.0
  }
}
```

**CLI config command:** `claude-spend config --plan max5`

### 4. Data Source Priority

When rendering quota widgets:
1. If OAuth `QuotaSnapshot` available → use it (most accurate)
2. Else if hook usage-log has data → compute estimated percentages from accumulated costs vs plan budgets
3. Else → show "No usage data. Run `claude-spend install-hook` or login with `claude login`."

## UI: Overview Tab — Quota Gauge Row

Added as a second row below existing BigNumber cards:

```
  Total Tokens    Est. API Cost    Sessions    Achievement
  1.23M           $45.67           42          85% (38f)

  5h Window                Weekly Quota            Sonnet Weekly
  ████████░░ 78%           ████░░░░░░ 42%          ██░░░░░░░░ 18%
  Resets: 2h 14m           Resets: 4d 6h           Resets: 4d 6h

  Plan: Max 5x ($100/mo)
```

### QuotaGauge Widget

New `Static` subclass rendering:
- Colored progress bar (width 10 chars): green (<60%), yellow/dark_orange (60-85%), red (>85%)
- Percentage label with matching color
- Reset countdown (if timestamp available) or "est." label for hook-only data
- Compact: fits in a `Horizontal` container with 3 gauges

### Fallback States

| State | Display |
|-|-|
| OAuth available | Real percentages + exact reset times |
| Hook-only | Estimated percentages + "~" prefix, no reset times |
| No data | `[dim]Run 'claude-spend install-hook' to track usage[/dim]` |

## UI: Dedicated "Limits" Tab

New tab positioned after "Sessions", before "Projects".

### Layout

```
  Plan: Max 5x ($100/mo)

  ┌─ 5h Session Window ─────────┐  ┌─ Weekly All Models ─────────┐  ┌─ Weekly Sonnet ─────────────┐
  │  ████████████████░░░░ 78%   │  │  ████████░░░░░░░░░░░░ 42%   │  │  ████░░░░░░░░░░░░░░░░ 18%   │
  │  Resets in 2h 14m           │  │  Resets in 4d 6h            │  │  Resets in 4d 6h            │
  │  Used: ~$3.40 / ~$4.40     │  │  Used: ~$45 / ~$100         │  │  Used: ~$8 / ~$44           │
  └─────────────────────────────┘  └─────────────────────────────┘  └─────────────────────────────┘

  RECENT SESSIONS (contribution to current windows)
  Time         Project          Cost     5h%    7d%
  14:23        claude-tui       $2.10    48%    2.1%
  12:05        my-app           $1.30    30%    1.3%
  09:15        docs             $0.45    10%    0.5%
  [yesterday]  my-app           $4.20     —     4.2%

  [Historical chart: daily peak 5h quota utilization over 30 days]
```

### QuotaCard Widget

Bordered container with:
- Title (e.g. "5h Session Window")
- Wide gauge bar (20 chars) with color coding
- Reset countdown
- Estimated cost used vs budget: `Used: ~${used:.2f} / ~${budget:.2f}`

### Recent Sessions Table

`DataTable` with sortable columns:
- **Time**: session start, relative format ("14:23", "yesterday", "3d ago")
- **Project**: project name
- **Cost**: session estimated cost
- **5h%**: this session's estimated share of the 5h window (blank if outside window)
- **7d%**: this session's estimated share of the 7d window

Data source: merge hook usage-log with parsed session data. Sessions outside the current 5h window show "—" in the 5h% column.

### Historical Chart

`PlotextPlot` showing daily peak 5h window utilization over the past 30 days:
- X-axis: dates
- Y-axis: estimated peak 5h% for that day (max cost in any 5h sliding window that day)
- Color: green/yellow/red bands at 60%/85% thresholds
- Source: computed from hook usage-log data

When insufficient historical data: show `[dim]Accumulating data... chart appears after 3+ days of hook data[/dim]`

## UI: Session Detail Enhancement

Add single line to existing expandable session detail panel:

```
PLAN USAGE  5h: ███░░ 12% of window   7d: █░░░░ 2.1% of weekly
```

Compact inline gauge showing this session's estimated contribution to each window.

## Hook Installation / Uninstallation

### `claude-spend install-hook`

1. Read `~/.claude/settings.json`
2. Add to `hooks.Stop`:
```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3 -m claude_spend.hook"
    }
  ]
}
```
3. Preserve existing hooks — append, don't overwrite
4. Create `~/.claude-spend/` directory if needed
5. Create default `~/.claude-spend/config.json` with plan prompt
6. Print confirmation: "Hook installed. Usage tracking is now active across all projects."

### `claude-spend uninstall-hook`

1. Read `~/.claude/settings.json`
2. Remove the claude-spend entry from `hooks.Stop`
3. Optionally clean up `~/.claude-spend/usage-log.jsonl` (prompt user)
4. Print confirmation

### Edge Cases

- If `settings.json` doesn't exist: create it with just the hook config
- If hook is already installed: skip, print "Already installed"
- If `settings.json` has other hooks: preserve them, only modify claude-spend entries
- Uninstall with no hook present: print "No hook found, nothing to remove"

## Test Plan

### Unit Tests (`tests/test_usage_api.py`)

1. **`test_parse_quota_snapshot`** — Parse a mock OAuth API response into `QuotaSnapshot`
2. **`test_missing_credentials`** — Return `None` when credentials file doesn't exist
3. **`test_expired_cache`** — Re-fetch when cache TTL exceeded
4. **`test_valid_cache`** — Return cached data when within TTL

### Unit Tests (`tests/test_hook.py`)

5. **`test_hook_extracts_usage`** — Given a session JSONL with known usage, verify correct extraction of token counts and cost
6. **`test_hook_deduplication`** — Running hook twice on same turn produces only one log entry
7. **`test_hook_appends_to_log`** — Verify JSONL append (not overwrite)
8. **`test_rolling_window_5h`** — Given usage-log entries spanning 6 hours, verify 5h window sums correctly
9. **`test_rolling_window_7d`** — Given usage-log entries spanning 8 days, verify 7d window sums correctly
10. **`test_session_contribution_pct`** — Verify per-session percentage calculation

### Unit Tests (`tests/test_hook_install.py`)

11. **`test_install_hook_fresh`** — Install into empty settings.json
12. **`test_install_hook_existing`** — Install preserving existing hooks
13. **`test_install_hook_idempotent`** — Second install is a no-op
14. **`test_uninstall_hook`** — Clean removal from settings.json
15. **`test_uninstall_hook_not_present`** — Graceful no-op when not installed

### Integration Tests (`tests/test_limits_tab.py`)

16. **`test_limits_tab_with_oauth`** — Mock OAuth response, verify gauge widgets render correct percentages
17. **`test_limits_tab_hook_only`** — No OAuth, but usage-log exists, verify estimated percentages display
18. **`test_limits_tab_no_data`** — No OAuth or hook data, verify fallback message
19. **`test_overview_quota_gauges`** — Verify quota row appears in Overview tab with correct data
20. **`test_session_detail_plan_usage`** — Verify PLAN USAGE line appears in session detail

### Plan Budget Tests

21. **`test_plan_budgets_pro`** — Verify Pro plan budget constants
22. **`test_plan_budgets_max5`** — Verify Max 5x budget constants
23. **`test_plan_budgets_max20`** — Verify Max 20x budget constants
24. **`test_custom_budgets`** — Verify user-configured custom budgets override defaults

## File Structure

```
claude_spend/
  usage_api.py      # OAuth API client + QuotaSnapshot dataclass
  hook.py           # Stop hook script + usage-log management + rolling window calc
  hook_install.py   # install/uninstall CLI commands
  plan_config.py    # Plan budget constants + config file management
  dashboard.py      # Modified: QuotaGauge, QuotaCard widgets, Limits tab, Overview row

tests/
  test_usage_api.py
  test_hook.py
  test_hook_install.py
  test_limits_tab.py
```

## Out of Scope

- Real-time WebSocket/SSE streaming of quota changes
- Proxy-based interception (claude-meter approach)
- Automatic plan detection (user must configure)
- Push notifications when approaching limits

## Open Questions (resolved)

- **Q:** Can we intercept Claude Code's internal limit tracking? **A:** No. No local storage of limits. OAuth API is the closest.
- **Q:** Are plan limits officially published? **A:** No. Community estimates used with configurable overrides.
- **Q:** Where do OAuth credentials live? **A:** `~/.claude/.credentials.json` (only exists for OAuth-logged-in users, not API key users)

## Sources

- [Faros.ai — Claude Code Token Limits Guide](https://www.faros.ai/blog/claude-code-token-limits)
- [Claude Help Center — Using Claude Code with Pro/Max](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
- [claude-code-statusline](https://github.com/ohugonnot/claude-code-statusline) — OAuth usage API discovery
- [claude-meter](https://github.com/abhishekray07/claude-meter) — Proxy-based rate limit header interception
