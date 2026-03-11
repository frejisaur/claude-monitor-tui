# Claude Spend TUI Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that launches a Textual TUI dashboard showing token usage analytics, cost estimates, and subagent breakdowns from `~/.claude/` session data.

**Architecture:** Plugin scaffold (`plugin.json`, `spend.md`, `requirements.txt`) wraps a Python Textual app. The app has two modules: `data.py` (parsing, aggregation, cost calculation) and `dashboard.py` (Textual UI with 6 tabs). Data layer reads session-meta JSON + conversation JSONLs, correlates subagent calls with their results, and computes per-model costs.

**Tech Stack:** Python 3.10+, Textual, textual-plotext, plotext

**Spec:** `docs/superpowers/specs/2026-03-10-claude-spend-tui-design.md`

---

## File Structure

```
claude-spend/                          # Standalone project at ~/code/claude-spend/
├── .claude-plugin/
│   └── plugin.json                    # Plugin manifest (name, description, version)
├── commands/
│   └── spend.md                       # /spend slash command — tells Claude to run dashboard.py
├── scripts/
│   ├── data.py                        # Data loading, parsing, aggregation, cost calculation
│   └── dashboard.py                   # Textual app — 6 tabs, imports from data.py
├── tests/
│   ├── conftest.py                    # Shared fixtures (fake session data, temp dirs)
│   ├── test_data_models.py            # TokenUsage, cost calculation tests
│   ├── test_session_parser.py         # JSONL parsing, session-meta reading tests
│   ├── test_subagent_parser.py        # Task call/result correlation, model extraction
│   └── test_aggregation.py            # Daily, project, model, subagent aggregation tests
├── requirements.txt                   # textual, textual-plotext, plotext
├── requirements-dev.txt               # pytest
└── setup.py                           # Minimal, for pip install -e .
```

**Note:** Spec says "single Python file" but we split data logic from UI for testability. `data.py` handles all computation; `dashboard.py` is pure presentation. This is the minimal split that keeps both files focused and testable.

---

## Chunk 1: Project Scaffold and Data Models

### Task 1: Create project scaffold

**Files:**
- Create: `~/code/claude-spend/.claude-plugin/plugin.json`
- Create: `~/code/claude-spend/commands/spend.md`
- Create: `~/code/claude-spend/requirements.txt`
- Create: `~/code/claude-spend/requirements-dev.txt`
- Create: `~/code/claude-spend/setup.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p ~/code/claude-spend/.claude-plugin
mkdir -p ~/code/claude-spend/commands
mkdir -p ~/code/claude-spend/scripts
mkdir -p ~/code/claude-spend/tests
```

- [ ] **Step 2: Write plugin.json**

Create `~/code/claude-spend/.claude-plugin/plugin.json`:
```json
{
  "name": "claude-spend",
  "description": "Token usage analytics dashboard for Claude Code",
  "version": "1.0.0",
  "author": {
    "name": "abiz"
  },
  "license": "MIT",
  "keywords": ["analytics", "tokens", "usage", "cost", "dashboard"]
}
```

- [ ] **Step 3: Write spend.md command**

Create `~/code/claude-spend/commands/spend.md`:
```markdown
---
description: "Launch token usage analytics dashboard"
---

Run the claude-spend TUI dashboard. Execute this command:

\`\`\`bash
cd "$HOME/code/claude-spend" && pip install -q -r requirements.txt 2>/dev/null && python3 scripts/dashboard.py --days $ARGUMENTS
\`\`\`

If $ARGUMENTS is empty, use `--days 30` as default.
Pass the user's argument as the --days value. Examples: `/spend 7` → `--days 7`, `/spend all` → `--days all`, `/spend` → `--days 30`.
```

- [ ] **Step 4: Write requirements files**

Create `~/code/claude-spend/requirements.txt`:
```
textual>=0.47.0
textual-plotext>=0.2.0
plotext>=5.2.0
```

Create `~/code/claude-spend/requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0.0
```

- [ ] **Step 5: Write minimal setup.py**

Create `~/code/claude-spend/setup.py`:
```python
from setuptools import setup, find_packages

setup(
    name="claude-spend",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "textual>=0.47.0",
        "textual-plotext>=0.2.0",
        "plotext>=5.2.0",
    ],
)
```

- [ ] **Step 6: Initialize git and commit**

```bash
cd ~/code/claude-spend
git init
git add .
git commit -m "chore: initial project scaffold"
```

---

### Task 2: Implement TokenUsage and cost calculation

**Files:**
- Create: `~/code/claude-spend/scripts/data.py`
- Create: `~/code/claude-spend/tests/test_data_models.py`

- [ ] **Step 1: Write tests for TokenUsage and cost calculation**

Create `~/code/claude-spend/tests/test_data_models.py`:
```python
from scripts.data import TokenUsage, PRICING, calculate_cost


def test_token_usage_total():
    usage = TokenUsage(input_tokens=1000, output_tokens=500, cache_write_tokens=200, cache_read_tokens=300)
    assert usage.total == 2000


def test_token_usage_zero():
    usage = TokenUsage()
    assert usage.total == 0


def test_token_usage_add():
    a = TokenUsage(input_tokens=100, output_tokens=50, cache_write_tokens=20, cache_read_tokens=30)
    b = TokenUsage(input_tokens=200, output_tokens=100, cache_write_tokens=40, cache_read_tokens=60)
    c = a + b
    assert c.input_tokens == 300
    assert c.output_tokens == 150
    assert c.cache_write_tokens == 60
    assert c.cache_read_tokens == 90


def test_calculate_cost_opus():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    cost = calculate_cost(usage, "claude-opus-4-6")
    # $15 input + $75 output + $18.75 cache_write + $1.50 cache_read = $110.25
    assert abs(cost - 110.25) < 0.01


def test_calculate_cost_sonnet():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    cost = calculate_cost(usage, "claude-sonnet-4-6")
    # $3 + $15 + $3.75 + $0.30 = $22.05
    assert abs(cost - 22.05) < 0.01


def test_calculate_cost_haiku():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    cost = calculate_cost(usage, "claude-haiku-4-5-20251001")
    # $0.80 + $4.00 + $1.00 + $0.08 = $5.88
    assert abs(cost - 5.88) < 0.01


def test_calculate_cost_unknown_model_falls_back_to_sonnet():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0, cache_write_tokens=0, cache_read_tokens=0)
    cost = calculate_cost(usage, "claude-unknown-model")
    # Falls back to sonnet: $3/MTok
    assert abs(cost - 3.0) < 0.01
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_data_models.py -v
```

Expected: `ModuleNotFoundError` — `scripts.data` doesn't exist yet.

- [ ] **Step 3: Implement TokenUsage and cost calculation**

Create `~/code/claude-spend/scripts/__init__.py` (empty) and `~/code/claude-spend/tests/__init__.py` (empty).

Create `~/code/claude-spend/scripts/data.py`:
```python
"""Data loading, parsing, aggregation, and cost calculation for claude-spend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Pricing in $/MTok
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
}

FALLBACK_MODEL = "claude-sonnet-4-6"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_write_tokens + self.cache_read_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )


def calculate_cost(usage: TokenUsage, model: str) -> float:
    """Calculate estimated API cost for a token usage at given model's pricing."""
    prices = PRICING.get(model, PRICING[FALLBACK_MODEL])
    return (
        (usage.input_tokens / 1_000_000) * prices["input"]
        + (usage.output_tokens / 1_000_000) * prices["output"]
        + (usage.cache_write_tokens / 1_000_000) * prices["cache_write"]
        + (usage.cache_read_tokens / 1_000_000) * prices["cache_read"]
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_data_models.py -v
```

Expected: All 7 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/code/claude-spend
git add scripts/ tests/
git commit -m "feat: add TokenUsage data model and cost calculation"
```

---

## Chunk 2: Session and JSONL Parsing

### Task 3: Implement session-meta loading with time filtering

**Files:**
- Modify: `~/code/claude-spend/scripts/data.py`
- Create: `~/code/claude-spend/tests/conftest.py`
- Create: `~/code/claude-spend/tests/test_session_parser.py`

- [ ] **Step 1: Write test fixtures**

Create `~/code/claude-spend/tests/conftest.py`:
```python
import json
import os
import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture
def tmp_claude_dir(tmp_path):
    """Create a fake ~/.claude/ structure with test data."""
    claude_dir = tmp_path / ".claude"
    meta_dir = claude_dir / "usage-data" / "session-meta"
    projects_dir = claude_dir / "projects"
    meta_dir.mkdir(parents=True)
    projects_dir.mkdir(parents=True)
    return claude_dir


@pytest.fixture
def sample_session_meta():
    """Return a valid session-meta dict."""
    return {
        "session_id": "abc-123",
        "project_path": "/Users/test/code/myproject",
        "start_time": "2026-03-05T10:00:00.000Z",
        "duration_minutes": 45,
        "user_message_count": 10,
        "assistant_message_count": 20,
        "tool_counts": {"Bash": 5, "Read": 3, "Task": 2},
        "input_tokens": 5000,
        "output_tokens": 12000,
        "first_prompt": "fix the authentication bug in login",
    }


@pytest.fixture
def sample_jsonl_messages():
    """Return a list of JSONL message dicts simulating a conversation."""
    return [
        # Assistant message with model and usage
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "content": [{"type": "text", "text": "I'll fix that."}],
                "usage": {
                    "input_tokens": 3000,
                    "output_tokens": 500,
                    "cache_creation_input_tokens": 1000,
                    "cache_read_input_tokens": 2000,
                },
            },
            "timestamp": "2026-03-05T10:01:00.000Z",
        },
        # Assistant message with Task tool call
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_abc123",
                        "name": "Task",
                        "input": {
                            "subagent_type": "Explore",
                            "description": "Find auth handler",
                            "prompt": "Search for the auth handler...",
                        },
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 500,
                },
            },
            "timestamp": "2026-03-05T10:02:00.000Z",
        },
        # Progress message from subagent with model
        {
            "type": "progress",
            "toolUseID": "toolu_abc123_sub",
            "parentToolUseID": "toolu_abc123",
            "data": {
                "type": "assistant",
                "message": {
                    "type": "assistant",
                    "message": {
                        "model": "claude-haiku-4-5-20251001",
                        "content": [{"type": "text", "text": "Found it"}],
                    },
                },
            },
        },
        # User message with Task tool result
        {
            "type": "user",
            "toolUseResult": {
                "status": "completed",
                "agentId": "agent-xyz",
                "totalDurationMs": 5000,
                "totalTokens": 15000,
                "totalToolUseCount": 3,
                "usage": {
                    "input_tokens": 2000,
                    "output_tokens": 800,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 11700,
                },
                "prompt": "Search for the auth handler...",
            },
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "content": "Found auth handler at src/auth.py",
                    }
                ],
            },
        },
        # Assistant message with Skill tool call
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_skill1",
                        "name": "Skill",
                        "input": {"skill": "superpowers:brainstorming"},
                    }
                ],
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 100,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 1000,
                },
            },
            "timestamp": "2026-03-05T10:05:00.000Z",
        },
    ]
```

- [ ] **Step 2: Write tests for session-meta loading**

Create `~/code/claude-spend/tests/test_session_parser.py`:
```python
import json
from datetime import datetime, timezone, timedelta
from scripts.data import load_session_metas, SessionMeta


def test_load_session_metas(tmp_claude_dir, sample_session_meta):
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    metas = load_session_metas(str(tmp_claude_dir))
    assert len(metas) == 1
    assert metas[0].session_id == "abc-123"
    assert metas[0].project_path == "/Users/test/code/myproject"
    assert metas[0].first_prompt == "fix the authentication bug in login"


def test_load_session_metas_filters_by_days(tmp_claude_dir, sample_session_meta):
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"

    # Recent session
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # Old session (60 days ago)
    old_meta = dict(sample_session_meta)
    old_meta["session_id"] = "old-456"
    old_meta["start_time"] = "2026-01-01T10:00:00.000Z"
    with open(meta_dir / "old-456.json", "w") as f:
        json.dump(old_meta, f)

    metas = load_session_metas(str(tmp_claude_dir), days=7)
    assert len(metas) == 1
    assert metas[0].session_id == "abc-123"


def test_load_session_metas_no_filter_for_all(tmp_claude_dir, sample_session_meta):
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"

    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    old_meta = dict(sample_session_meta)
    old_meta["session_id"] = "old-456"
    old_meta["start_time"] = "2025-01-01T10:00:00.000Z"
    with open(meta_dir / "old-456.json", "w") as f:
        json.dump(old_meta, f)

    metas = load_session_metas(str(tmp_claude_dir), days=None)
    assert len(metas) == 2


def test_load_session_metas_skips_malformed(tmp_claude_dir):
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "bad.json", "w") as f:
        f.write("not valid json{{{")

    metas = load_session_metas(str(tmp_claude_dir))
    assert len(metas) == 0


def test_load_session_metas_empty_dir(tmp_claude_dir):
    metas = load_session_metas(str(tmp_claude_dir))
    assert len(metas) == 0
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_session_parser.py -v
```

Expected: `ImportError` — `load_session_metas` and `SessionMeta` not defined.

- [ ] **Step 4: Implement session-meta loading**

Add to `~/code/claude-spend/scripts/data.py`:
```python
import json
import glob
import os

@dataclass
class SessionMeta:
    session_id: str
    project_path: str
    project_name: str
    start_time: datetime
    duration_minutes: int
    first_prompt: str
    tool_counts: dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0


def _parse_start_time(time_str: str) -> datetime:
    """Parse ISO 8601 timestamp to datetime."""
    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))


def _project_name_from_path(path: str) -> str:
    """Extract short project name from full path. '/Users/foo/code/bar' -> 'bar'."""
    return os.path.basename(path.rstrip("/")) or path


def load_session_metas(claude_dir: str, days: int | None = 30) -> list[SessionMeta]:
    """Load session metadata files, optionally filtered to last N days."""
    meta_dir = os.path.join(claude_dir, "usage-data", "session-meta")
    if not os.path.isdir(meta_dir):
        return []

    cutoff = None
    if days is not None:
        from datetime import timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    results = []
    for path in glob.glob(os.path.join(meta_dir, "*.json")):
        try:
            with open(path) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        start_time = _parse_start_time(raw.get("start_time", "1970-01-01T00:00:00Z"))
        if cutoff and start_time < cutoff:
            continue

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
        ))

    results.sort(key=lambda s: s.start_time, reverse=True)
    return results
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_session_parser.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 6: Commit**

```bash
cd ~/code/claude-spend
git add scripts/data.py tests/
git commit -m "feat: add session-meta loading with time range filtering"
```

---

### Task 4: Implement JSONL conversation parsing

**Files:**
- Modify: `~/code/claude-spend/scripts/data.py`
- Modify: `~/code/claude-spend/tests/test_session_parser.py`

- [ ] **Step 1: Write tests for JSONL parsing**

Add to `~/code/claude-spend/tests/test_session_parser.py`:
```python
from scripts.data import parse_conversation_jsonl, ConversationData


def _write_jsonl(path, messages):
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_parse_conversation_extracts_model_usage(tmp_path, sample_jsonl_messages):
    jsonl_path = tmp_path / "session.jsonl"
    _write_jsonl(jsonl_path, sample_jsonl_messages)

    data = parse_conversation_jsonl(str(jsonl_path))

    # Should have usage from 3 assistant messages (msg 0, 1, 4)
    assert "claude-opus-4-6" in data.usage_by_model
    opus_usage = data.usage_by_model["claude-opus-4-6"]
    assert opus_usage.input_tokens == 3000 + 100 + 200  # 3 assistant msgs
    assert opus_usage.output_tokens == 500 + 50 + 100


def test_parse_conversation_extracts_subagent_calls(tmp_path, sample_jsonl_messages):
    jsonl_path = tmp_path / "session.jsonl"
    _write_jsonl(jsonl_path, sample_jsonl_messages)

    data = parse_conversation_jsonl(str(jsonl_path))

    assert len(data.subagent_calls) == 1
    call = data.subagent_calls[0]
    assert call.subagent_type == "Explore"
    assert call.description == "Find auth handler"
    assert call.model == "claude-haiku-4-5-20251001"
    assert call.duration_ms == 5000
    assert call.tool_use_count == 3
    assert call.usage.input_tokens == 2000
    assert call.usage.output_tokens == 800


def test_parse_conversation_extracts_skills(tmp_path, sample_jsonl_messages):
    jsonl_path = tmp_path / "session.jsonl"
    _write_jsonl(jsonl_path, sample_jsonl_messages)

    data = parse_conversation_jsonl(str(jsonl_path))
    assert "superpowers:brainstorming" in data.skill_invocations


def test_parse_conversation_handles_malformed_lines(tmp_path):
    jsonl_path = tmp_path / "session.jsonl"
    with open(jsonl_path, "w") as f:
        f.write("not json\n")
        f.write(json.dumps({"type": "assistant", "message": {
            "model": "claude-opus-4-6",
            "content": [],
            "usage": {"input_tokens": 100, "output_tokens": 50,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        }}) + "\n")

    data = parse_conversation_jsonl(str(jsonl_path))
    assert data.parse_errors == 1
    assert "claude-opus-4-6" in data.usage_by_model


def test_parse_conversation_missing_file():
    data = parse_conversation_jsonl("/nonexistent/path.jsonl")
    assert data.usage_by_model == {}
    assert data.subagent_calls == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_session_parser.py::test_parse_conversation_extracts_model_usage -v
```

Expected: `ImportError` — `parse_conversation_jsonl` not defined.

- [ ] **Step 3: Implement JSONL parsing**

Add to `~/code/claude-spend/scripts/data.py`:
```python
@dataclass
class SubagentCall:
    session_id: str = ""
    subagent_type: str = ""
    description: str = ""
    model: str = "unknown"
    usage: TokenUsage = field(default_factory=TokenUsage)
    duration_ms: int = 0
    tool_use_count: int = 0


@dataclass
class ConversationData:
    usage_by_model: dict[str, TokenUsage] = field(default_factory=dict)
    subagent_calls: list[SubagentCall] = field(default_factory=list)
    skill_invocations: list[str] = field(default_factory=list)
    parse_errors: int = 0


def parse_conversation_jsonl(jsonl_path: str) -> ConversationData:
    """Parse a conversation JSONL file, extracting per-model usage, subagent calls, and skills."""
    data = ConversationData()

    if not os.path.isfile(jsonl_path):
        return data

    # First pass: collect Task tool call info and subagent models from progress messages
    task_calls: dict[str, dict] = {}       # tool_use_id -> {subagent_type, description, model_param}
    subagent_models: dict[str, str] = {}   # parentToolUseID -> model from progress

    lines = []
    with open(jsonl_path) as f:
        for line in f:
            try:
                msg = json.loads(line)
                lines.append(msg)
            except json.JSONDecodeError:
                data.parse_errors += 1

    for msg in lines:
        msg_type = msg.get("type")

        if msg_type == "assistant":
            inner = msg.get("message", {})
            # Extract per-model token usage
            model = inner.get("model")
            usage_raw = inner.get("usage", {})
            if model and usage_raw:
                usage = TokenUsage(
                    input_tokens=usage_raw.get("input_tokens", 0),
                    output_tokens=usage_raw.get("output_tokens", 0),
                    cache_write_tokens=usage_raw.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
                )
                if model in data.usage_by_model:
                    data.usage_by_model[model] = data.usage_by_model[model] + usage
                else:
                    data.usage_by_model[model] = usage

            # Extract Task and Skill tool calls
            for block in inner.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") == "Task":
                    inp = block.get("input", {})
                    task_calls[block["id"]] = {
                        "subagent_type": inp.get("subagent_type", "unknown"),
                        "description": inp.get("description", ""),
                        "model_param": inp.get("model"),
                    }
                elif block.get("name") == "Skill":
                    skill_name = block.get("input", {}).get("skill", "")
                    if skill_name:
                        data.skill_invocations.append(skill_name)

        elif msg_type == "progress":
            parent_id = msg.get("parentToolUseID")
            if parent_id and parent_id not in subagent_models:
                # Try to extract model from nested assistant message
                inner_data = msg.get("data", {})
                inner_msg = inner_data.get("message", {})
                if isinstance(inner_msg, dict):
                    nested = inner_msg.get("message", {})
                    if isinstance(nested, dict) and "model" in nested:
                        subagent_models[parent_id] = nested["model"]

        elif msg_type == "user":
            result = msg.get("toolUseResult")
            if not isinstance(result, dict) or "totalTokens" not in result:
                continue

            # Find the matching Task call via tool_result content
            tool_use_id = None
            user_msg = msg.get("message", {})
            for block in user_msg.get("content", []) if isinstance(user_msg, dict) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    break

            if tool_use_id and tool_use_id in task_calls:
                call_info = task_calls[tool_use_id]
                usage_raw = result.get("usage", {})
                model = (
                    call_info["model_param"]
                    or subagent_models.get(tool_use_id, "unknown")
                )
                data.subagent_calls.append(SubagentCall(
                    subagent_type=call_info["subagent_type"],
                    description=call_info["description"],
                    model=model,
                    usage=TokenUsage(
                        input_tokens=usage_raw.get("input_tokens", 0),
                        output_tokens=usage_raw.get("output_tokens", 0),
                        cache_write_tokens=usage_raw.get("cache_creation_input_tokens", 0),
                        cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
                    ),
                    duration_ms=result.get("totalDurationMs", 0),
                    tool_use_count=result.get("totalToolUseCount", 0),
                ))

    return data
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_session_parser.py -v
```

Expected: All 10 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/code/claude-spend
git add scripts/data.py tests/
git commit -m "feat: add JSONL conversation parser with subagent and skill extraction"
```

---

## Chunk 3: Aggregation and Full Data Pipeline

### Task 5: Implement aggregation functions

**Files:**
- Modify: `~/code/claude-spend/scripts/data.py`
- Create: `~/code/claude-spend/tests/test_aggregation.py`

- [ ] **Step 1: Write tests for aggregation**

Create `~/code/claude-spend/tests/test_aggregation.py`:
```python
import json
from scripts.data import (
    TokenUsage, SessionSummary, SubagentCall,
    aggregate_by_day, aggregate_by_project, aggregate_by_model, aggregate_by_subagent_type,
    DailyAggregate, ProjectAggregate, ModelAggregate, SubagentTypeAggregate,
)
from datetime import datetime, timezone


def _make_session(session_id, project, date_str, model="claude-opus-4-6", tokens=1000):
    usage = TokenUsage(input_tokens=tokens, output_tokens=tokens // 2, cache_write_tokens=0, cache_read_tokens=0)
    return SessionSummary(
        session_id=session_id,
        project_path=f"/Users/test/code/{project}",
        project_name=project,
        start_time=datetime.fromisoformat(f"{date_str}T10:00:00+00:00"),
        duration_minutes=30,
        first_prompt="test prompt",
        usage_by_model={model: usage},
        tool_counts={},
        subagent_calls=[],
        skill_invocations=[],
        estimated_cost=0.0,
    )


def test_aggregate_by_day():
    sessions = [
        _make_session("s1", "proj", "2026-03-05", tokens=1000),
        _make_session("s2", "proj", "2026-03-05", tokens=2000),
        _make_session("s3", "proj", "2026-03-06", tokens=500),
    ]
    daily = aggregate_by_day(sessions)
    assert len(daily) == 2
    # Sorted by date
    assert daily[0].date == "2026-03-05"
    assert daily[0].session_count == 2
    assert daily[1].date == "2026-03-06"
    assert daily[1].session_count == 1


def test_aggregate_by_project():
    sessions = [
        _make_session("s1", "alpha", "2026-03-05"),
        _make_session("s2", "alpha", "2026-03-06"),
        _make_session("s3", "beta", "2026-03-05"),
    ]
    projects = aggregate_by_project(sessions)
    assert len(projects) == 2
    alpha = next(p for p in projects if p.project_name == "alpha")
    assert alpha.session_count == 2


def test_aggregate_by_model():
    s1 = _make_session("s1", "proj", "2026-03-05", model="claude-opus-4-6", tokens=1000)
    s2 = _make_session("s2", "proj", "2026-03-05", model="claude-haiku-4-5-20251001", tokens=500)
    models = aggregate_by_model([s1, s2])
    assert len(models) == 2
    opus = next(m for m in models if m.model == "claude-opus-4-6")
    assert opus.total_usage.input_tokens == 1000


def test_aggregate_by_subagent_type():
    call1 = SubagentCall(
        session_id="s1", subagent_type="Explore", description="Find X",
        model="claude-haiku-4-5-20251001",
        usage=TokenUsage(input_tokens=5000, output_tokens=1000, cache_write_tokens=0, cache_read_tokens=0),
        duration_ms=3000, tool_use_count=2,
    )
    call2 = SubagentCall(
        session_id="s1", subagent_type="Explore", description="Find Y",
        model="claude-haiku-4-5-20251001",
        usage=TokenUsage(input_tokens=3000, output_tokens=800, cache_write_tokens=0, cache_read_tokens=0),
        duration_ms=2000, tool_use_count=1,
    )
    call3 = SubagentCall(
        session_id="s1", subagent_type="Plan", description="Plan Z",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input_tokens=10000, output_tokens=5000, cache_write_tokens=0, cache_read_tokens=0),
        duration_ms=8000, tool_use_count=5,
    )
    aggs = aggregate_by_subagent_type([call1, call2, call3])
    assert len(aggs) == 2
    explore = next(a for a in aggs if a.subagent_type == "Explore")
    assert explore.call_count == 2
    assert explore.total_usage.input_tokens == 8000
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_aggregation.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement aggregation functions and remaining dataclasses**

Add to `~/code/claude-spend/scripts/data.py`:
```python
from collections import defaultdict


@dataclass
class SessionSummary:
    session_id: str = ""
    project_path: str = ""
    project_name: str = ""
    start_time: datetime = field(default_factory=lambda: datetime(1970, 1, 1))
    duration_minutes: int = 0
    first_prompt: str = ""
    usage_by_model: dict[str, TokenUsage] = field(default_factory=dict)
    tool_counts: dict[str, int] = field(default_factory=dict)
    subagent_calls: list[SubagentCall] = field(default_factory=list)
    skill_invocations: list[str] = field(default_factory=list)
    estimated_cost: float = 0.0

    @property
    def total_usage(self) -> TokenUsage:
        result = TokenUsage()
        for u in self.usage_by_model.values():
            result = result + u
        return result


@dataclass
class DailyAggregate:
    date: str = ""
    usage_by_model: dict[str, TokenUsage] = field(default_factory=dict)
    session_count: int = 0
    estimated_cost: float = 0.0


@dataclass
class ProjectAggregate:
    project_name: str = ""
    project_path: str = ""
    session_count: int = 0
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost: float = 0.0


@dataclass
class ModelAggregate:
    model: str = ""
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    session_count: int = 0
    estimated_cost: float = 0.0


@dataclass
class SubagentTypeAggregate:
    subagent_type: str = ""
    call_count: int = 0
    models_used: dict[str, int] = field(default_factory=dict)
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    avg_tokens_per_call: int = 0
    total_duration_ms: int = 0
    estimated_cost: float = 0.0


def aggregate_by_day(sessions: list[SessionSummary]) -> list[DailyAggregate]:
    by_day: dict[str, DailyAggregate] = {}
    for s in sessions:
        date_str = s.start_time.strftime("%Y-%m-%d")
        if date_str not in by_day:
            by_day[date_str] = DailyAggregate(date=date_str)
        agg = by_day[date_str]
        agg.session_count += 1
        for model, usage in s.usage_by_model.items():
            if model in agg.usage_by_model:
                agg.usage_by_model[model] = agg.usage_by_model[model] + usage
            else:
                agg.usage_by_model[model] = TokenUsage(
                    usage.input_tokens, usage.output_tokens,
                    usage.cache_write_tokens, usage.cache_read_tokens,
                )
        agg.estimated_cost += s.estimated_cost
    return sorted(by_day.values(), key=lambda d: d.date)


def aggregate_by_project(sessions: list[SessionSummary]) -> list[ProjectAggregate]:
    by_proj: dict[str, ProjectAggregate] = {}
    for s in sessions:
        key = s.project_name
        if key not in by_proj:
            by_proj[key] = ProjectAggregate(project_name=key, project_path=s.project_path)
        agg = by_proj[key]
        agg.session_count += 1
        agg.total_usage = agg.total_usage + s.total_usage
        agg.estimated_cost += s.estimated_cost
    return sorted(by_proj.values(), key=lambda p: p.estimated_cost, reverse=True)


def aggregate_by_model(sessions: list[SessionSummary]) -> list[ModelAggregate]:
    by_model: dict[str, ModelAggregate] = {}
    for s in sessions:
        for model, usage in s.usage_by_model.items():
            if model not in by_model:
                by_model[model] = ModelAggregate(model=model)
            agg = by_model[model]
            agg.total_usage = agg.total_usage + usage
            agg.session_count += 1
            agg.estimated_cost += calculate_cost(usage, model)
    return sorted(by_model.values(), key=lambda m: m.estimated_cost, reverse=True)


def aggregate_by_subagent_type(calls: list[SubagentCall]) -> list[SubagentTypeAggregate]:
    by_type: dict[str, SubagentTypeAggregate] = {}
    for c in calls:
        key = c.subagent_type
        if key not in by_type:
            by_type[key] = SubagentTypeAggregate(subagent_type=key)
        agg = by_type[key]
        agg.call_count += 1
        agg.total_usage = agg.total_usage + c.usage
        agg.total_duration_ms += c.duration_ms
        agg.models_used[c.model] = agg.models_used.get(c.model, 0) + 1
        agg.estimated_cost += calculate_cost(c.usage, c.model)

    for agg in by_type.values():
        if agg.call_count > 0:
            agg.avg_tokens_per_call = agg.total_usage.total // agg.call_count

    return sorted(by_type.values(), key=lambda a: a.estimated_cost, reverse=True)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_aggregation.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/code/claude-spend
git add scripts/data.py tests/
git commit -m "feat: add aggregation functions (daily, project, model, subagent)"
```

---

### Task 6: Implement full data pipeline (load_all)

**Files:**
- Modify: `~/code/claude-spend/scripts/data.py`
- Modify: `~/code/claude-spend/tests/test_aggregation.py`

- [ ] **Step 1: Write test for load_all pipeline**

Add to `~/code/claude-spend/tests/test_aggregation.py`:
```python
from scripts.data import load_all, DashboardData


def test_load_all_integrates_meta_and_jsonl(tmp_claude_dir, sample_session_meta, sample_jsonl_messages):
    # Write session meta
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # Write JSONL in the right project directory
    project_encoded = sample_session_meta["project_path"].replace("/", "-")
    project_dir = tmp_claude_dir / "projects" / project_encoded
    project_dir.mkdir(parents=True)
    jsonl_path = project_dir / "abc-123.jsonl"
    with open(jsonl_path, "w") as f:
        for msg in sample_jsonl_messages:
            f.write(json.dumps(msg) + "\n")

    data = load_all(str(tmp_claude_dir), days=None)

    assert len(data.sessions) == 1
    session = data.sessions[0]
    assert "claude-opus-4-6" in session.usage_by_model
    assert len(session.subagent_calls) == 1
    assert session.estimated_cost > 0
    assert len(data.daily) >= 1
    assert len(data.projects) >= 1
    assert len(data.models) >= 1
    assert len(data.subagent_types) >= 1


def test_load_all_missing_claude_dir():
    data = load_all("/nonexistent/path", days=30)
    assert len(data.sessions) == 0


def test_load_all_session_without_jsonl_uses_meta_fallback(tmp_claude_dir, sample_session_meta):
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # No JSONL file — should still produce a session from meta
    data = load_all(str(tmp_claude_dir), days=None)
    assert len(data.sessions) == 1
    session = data.sessions[0]
    # Fallback uses meta totals with "unknown" model
    assert session.total_usage.input_tokens == sample_session_meta["input_tokens"]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_aggregation.py::test_load_all_integrates_meta_and_jsonl -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement load_all**

Add to `~/code/claude-spend/scripts/data.py`:
```python
@dataclass
class DashboardData:
    sessions: list[SessionSummary] = field(default_factory=list)
    daily: list[DailyAggregate] = field(default_factory=list)
    projects: list[ProjectAggregate] = field(default_factory=list)
    models: list[ModelAggregate] = field(default_factory=list)
    subagent_types: list[SubagentTypeAggregate] = field(default_factory=list)
    all_subagent_calls: list[SubagentCall] = field(default_factory=list)
    total_cost: float = 0.0
    total_tokens: int = 0
    parse_errors: int = 0


def _find_jsonl(claude_dir: str, meta: SessionMeta) -> str | None:
    """Find the conversation JSONL for a session across project directories."""
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return None

    project_encoded = meta.project_path.replace("/", "-")
    jsonl_path = os.path.join(projects_dir, project_encoded, f"{meta.session_id}.jsonl")
    if os.path.isfile(jsonl_path):
        return jsonl_path
    return None


def load_all(claude_dir: str, days: int | None = 30) -> DashboardData:
    """Load all data and produce aggregated dashboard data."""
    if not os.path.isdir(claude_dir):
        return DashboardData()

    metas = load_session_metas(claude_dir, days=days)
    sessions: list[SessionSummary] = []
    all_subagent_calls: list[SubagentCall] = []
    total_parse_errors = 0

    for meta in metas:
        jsonl_path = _find_jsonl(claude_dir, meta)

        if jsonl_path:
            conv = parse_conversation_jsonl(jsonl_path)
            total_parse_errors += conv.parse_errors

            # Calculate cost per model
            cost = sum(calculate_cost(u, m) for m, u in conv.usage_by_model.items())

            for call in conv.subagent_calls:
                call.session_id = meta.session_id

            session = SessionSummary(
                session_id=meta.session_id,
                project_path=meta.project_path,
                project_name=meta.project_name,
                start_time=meta.start_time,
                duration_minutes=meta.duration_minutes,
                first_prompt=meta.first_prompt,
                usage_by_model=conv.usage_by_model,
                tool_counts=meta.tool_counts,
                subagent_calls=conv.subagent_calls,
                skill_invocations=conv.skill_invocations,
                estimated_cost=cost,
            )
        else:
            # Fallback: use session-meta totals
            fallback_usage = TokenUsage(
                input_tokens=meta.input_tokens,
                output_tokens=meta.output_tokens,
            )
            cost = calculate_cost(fallback_usage, FALLBACK_MODEL)
            session = SessionSummary(
                session_id=meta.session_id,
                project_path=meta.project_path,
                project_name=meta.project_name,
                start_time=meta.start_time,
                duration_minutes=meta.duration_minutes,
                first_prompt=meta.first_prompt,
                usage_by_model={"unknown": fallback_usage},
                tool_counts=meta.tool_counts,
                estimated_cost=cost,
            )

        sessions.append(session)
        all_subagent_calls.extend(session.subagent_calls)

    total_cost = sum(s.estimated_cost for s in sessions)
    total_tokens = sum(s.total_usage.total for s in sessions)

    return DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type(all_subagent_calls),
        all_subagent_calls=sorted(all_subagent_calls, key=lambda c: c.usage.total, reverse=True),
        total_cost=total_cost,
        total_tokens=total_tokens,
        parse_errors=total_parse_errors,
    )
```

- [ ] **Step 4: Run all tests**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/ -v
```

Expected: All tests pass (data models + session parsing + aggregation + load_all).

- [ ] **Step 5: Commit**

```bash
cd ~/code/claude-spend
git add scripts/data.py tests/
git commit -m "feat: add load_all pipeline integrating meta + JSONL + aggregation"
```

---

## Chunk 4: Textual Dashboard UI

### Task 7: Implement dashboard app shell with Overview tab

**Files:**
- Create: `~/code/claude-spend/scripts/dashboard.py`

- [ ] **Step 1: Create the Textual app with Overview tab**

Create `~/code/claude-spend/scripts/dashboard.py`:
```python
"""Claude Spend — Token usage analytics dashboard for Claude Code."""

from __future__ import annotations

import argparse
import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import (
    Header, Footer, Static, Label, DataTable, TabbedContent, TabPane, Sparkline,
)

from data import load_all, DashboardData, calculate_cost


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

                # Sparkline of daily token totals
                daily_totals = [
                    float(sum(u.total for u in d.usage_by_model.values()))
                    for d in self.data.daily
                ]
                if daily_totals:
                    yield Label(f"Daily Token Usage ({self.days_label})")
                    yield Sparkline(data=daily_totals, summary_function=max, id="overview-sparkline")

            with TabPane("Sessions", id="tab-sessions"):
                yield DataTable(id="sessions-table")

            with TabPane("Projects", id="tab-projects"):
                yield DataTable(id="projects-table")

            with TabPane("Models", id="tab-models"):
                yield DataTable(id="models-table")

            with TabPane("Subagents", id="tab-subagents"):
                yield DataTable(id="subagents-table")

            with TabPane("Costs", id="tab-costs"):
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

    def _populate_sessions_table(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Date", "Project", "First Prompt", "Duration", "Tokens", "Cost")
        for s in sorted(self.data.sessions, key=lambda x: x.estimated_cost, reverse=True):
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

    def _populate_costs_table(self) -> None:
        table = self.query_one("#costs-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Model", "Input Cost", "Output Cost", "Cache Write Cost", "Cache Read Cost", "Total")
        for m in self.data.models:
            from data import PRICING, FALLBACK_MODEL
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
```

- [ ] **Step 2: Manual smoke test**

```bash
cd ~/code/claude-spend/scripts
pip install -r ../requirements.txt
python3 dashboard.py --days 7
```

**Validation checklist** (verify each before proceeding):
- [ ] TUI launches without exceptions
- [ ] Overview tab: 3 BigNumber widgets visible with non-zero values
- [ ] Sessions tab: DataTable has rows, columns show Date/Project/Prompt/Duration/Tokens/Cost
- [ ] Projects tab: DataTable groups sessions by project name
- [ ] Models tab: DataTable shows opus/sonnet/haiku rows with token breakdowns
- [ ] Subagents tab: DataTable shows subagent types (or empty message if none)
- [ ] Costs tab: DataTable shows per-model cost breakdown by token type
- [ ] Tab switching works (click or keyboard)
- [ ] Press `q` exits cleanly

**Corrective loop:** If any checklist item fails:
1. Capture the error/traceback or describe the visual defect
2. Fix `dashboard.py` (layout, widget config, data wiring)
3. Re-run `python3 dashboard.py --days 7` and re-check the failing items
4. Repeat until all items pass — do NOT commit until the full checklist is green

- [ ] **Step 3: Commit**

```bash
cd ~/code/claude-spend
git add scripts/dashboard.py
git commit -m "feat: add Textual dashboard app with all 6 tabs"
```

---

### Task 8: Add plotext charts to Overview, Models, and Subagents tabs

**Files:**
- Modify: `~/code/claude-spend/scripts/dashboard.py`

- [ ] **Step 1: Add plotext charts**

Add `from textual_plotext import PlotextPlot` to imports.

Replace the Overview tab's sparkline section with a PlotextPlot for a stacked daily bar chart. Add PlotextPlot widgets to Models tab (daily usage by model stacked bar) and Subagents tab (bar chart by type).

In `compose()`, within the Overview TabPane, after the big numbers:
```python
yield PlotextPlot(id="overview-chart")
```

In Models TabPane, before the DataTable:
```python
yield PlotextPlot(id="models-chart")
```

In Subagents TabPane, before the DataTable:
```python
yield PlotextPlot(id="subagents-chart")
```

In Costs TabPane, before the DataTable:
```python
yield PlotextPlot(id="costs-chart")
```

Add these CSS rules:
```css
PlotextPlot {
    height: 15;
    margin: 0 1;
}
```

Add chart population methods called from `on_mount()`:
```python
def _populate_overview_chart(self) -> None:
    plt = self.query_one("#overview-chart", PlotextPlot).plt
    plt.title("Daily Token Usage")
    plt.theme("textual-design-dark")

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
    plt = self.query_one("#models-chart", PlotextPlot).plt
    plt.title("Cost by Model")
    plt.theme("textual-design-dark")

    names = [m.model.split("-")[1] if "-" in m.model else m.model for m in self.data.models]
    costs = [m.estimated_cost for m in self.data.models]
    plt.bar(names, costs, color="blue")

def _populate_subagents_chart(self) -> None:
    plt = self.query_one("#subagents-chart", PlotextPlot).plt
    plt.title("Token Usage by Subagent Type")
    plt.theme("textual-design-dark")

    types = [a.subagent_type for a in self.data.subagent_types]
    tokens = [a.total_usage.total for a in self.data.subagent_types]
    plt.bar(types, tokens, color="green")

def _populate_costs_chart(self) -> None:
    plt = self.query_one("#costs-chart", PlotextPlot).plt
    plt.title("Daily Cost by Token Type")
    plt.theme("textual-design-dark")

    dates = [d.date[5:] for d in self.data.daily]
    colors = ["red", "orange", "yellow", "green"]
    labels = ["Input", "Output", "Cache Write", "Cache Read"]

    for i, (label, attr) in enumerate(zip(labels, ["input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens"])):
        values = []
        for d in self.data.daily:
            total = sum(getattr(u, attr) for u in d.usage_by_model.values())
            values.append(total)
        plt.bar(dates, values, label=label, color=colors[i])
```

- [ ] **Step 2: Manual smoke test**

```bash
cd ~/code/claude-spend/scripts
python3 dashboard.py --days 30
```

**Validation checklist**:
- [ ] Overview tab: bar chart renders with colored bars (not blank/error)
- [ ] Models tab: "Cost by Model" bar chart shows bars for each model
- [ ] Subagents tab: "Token Usage by Subagent Type" chart renders (or is absent if no subagent data)
- [ ] Costs tab: "Daily Cost by Token Type" chart renders with legend
- [ ] Charts scale correctly — no overlapping labels, bars are proportional
- [ ] Resize terminal: charts reflow without crashing

**Corrective loop:** If any chart fails:
1. If crash/traceback: fix the `_populate_*_chart` method (common issues: empty data arrays passed to plotext, mismatched list lengths)
2. If chart renders blank: verify the data pipeline produces non-empty `daily`/`models`/`subagent_types` lists — add debug print if needed
3. If layout is broken (overlap, truncation): adjust CSS height/margin or plotext `plt.plotsize()`
4. Re-run and re-check. Do NOT commit until all items pass.

- [ ] **Step 3: Commit**

```bash
cd ~/code/claude-spend
git add scripts/dashboard.py
git commit -m "feat: add plotext charts to overview, models, subagents, and costs tabs"
```

---

### Task 9: Automated TUI tests (Pilot + Snapshot)

**Files:**
- Modify: `~/code/claude-spend/requirements-dev.txt`
- Create: `~/code/claude-spend/tests/test_dashboard.py`

- [ ] **Step 1: Add test dependencies**

Add to `~/code/claude-spend/requirements-dev.txt`:
```
pytest-textual-snapshot>=1.0.0
```

Install:
```bash
cd ~/code/claude-spend && pip install -r requirements-dev.txt
```

- [ ] **Step 2: Write Pilot tests for widget population**

Create `~/code/claude-spend/tests/test_dashboard.py`:
```python
"""Automated TUI tests using Textual's Pilot (headless app runner)."""

import pytest
from datetime import datetime, timezone

from scripts.data import (
    DashboardData, SessionSummary, TokenUsage, SubagentCall,
    DailyAggregate, ProjectAggregate, ModelAggregate, SubagentTypeAggregate,
    calculate_cost,
    aggregate_by_day, aggregate_by_project, aggregate_by_model, aggregate_by_subagent_type,
)


def _make_test_data() -> DashboardData:
    """Build realistic fixture data without touching the filesystem."""
    sessions = []
    all_calls = []
    for i, (proj, model, tokens) in enumerate([
        ("alpha", "claude-opus-4-6", 50000),
        ("alpha", "claude-sonnet-4-6", 30000),
        ("beta", "claude-haiku-4-5-20251001", 10000),
    ]):
        usage = TokenUsage(input_tokens=tokens, output_tokens=tokens // 2,
                           cache_write_tokens=tokens // 10, cache_read_tokens=tokens * 2)
        cost = calculate_cost(usage, model)
        calls = []
        if i == 0:
            sub_usage = TokenUsage(input_tokens=5000, output_tokens=2000,
                                   cache_write_tokens=0, cache_read_tokens=8000)
            calls = [SubagentCall(
                session_id=f"s{i}", subagent_type="Explore", description="Find files",
                model="claude-haiku-4-5-20251001", usage=sub_usage,
                duration_ms=3000, tool_use_count=4,
            )]
        sessions.append(SessionSummary(
            session_id=f"s{i}", project_path=f"/code/{proj}", project_name=proj,
            start_time=datetime(2026, 3, 5 + i, 10, 0, tzinfo=timezone.utc),
            duration_minutes=30 + i * 10, first_prompt=f"Task {i}: do something",
            usage_by_model={model: usage}, tool_counts={"Bash": 3, "Read": 2},
            subagent_calls=calls, skill_invocations=[], estimated_cost=cost,
        ))
        all_calls.extend(calls)

    return DashboardData(
        sessions=sessions,
        daily=aggregate_by_day(sessions),
        projects=aggregate_by_project(sessions),
        models=aggregate_by_model(sessions),
        subagent_types=aggregate_by_subagent_type(all_calls),
        all_subagent_calls=all_calls,
        total_cost=sum(s.estimated_cost for s in sessions),
        total_tokens=sum(s.total_usage.total for s in sessions),
    )


def _make_empty_data() -> DashboardData:
    return DashboardData()


# ---- Pilot tests ----

@pytest.mark.asyncio
async def test_app_mounts_with_data():
    """App renders all tabs and widgets with valid data."""
    from scripts.dashboard import SpendApp
    from textual.widgets import DataTable, Static

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        # Overview tab big numbers should be present
        big_numbers = app.query("BigNumber")
        assert len(big_numbers) == 3

        # Sessions table should have rows
        sessions_table = app.query_one("#sessions-table", DataTable)
        assert sessions_table.row_count == 3

        # Switch to Projects tab
        await pilot.click("Projects")
        await pilot.pause()
        projects_table = app.query_one("#projects-table", DataTable)
        assert projects_table.row_count == 2  # alpha + beta

        # Switch to Models tab
        await pilot.click("Models")
        await pilot.pause()
        models_table = app.query_one("#models-table", DataTable)
        assert models_table.row_count == 3  # opus + sonnet + haiku

        # Switch to Subagents tab
        await pilot.click("Subagents")
        await pilot.pause()
        subagents_table = app.query_one("#subagents-table", DataTable)
        assert subagents_table.row_count >= 1  # at least Explore

        # Switch to Costs tab
        await pilot.click("Costs")
        await pilot.pause()
        costs_table = app.query_one("#costs-table", DataTable)
        assert costs_table.row_count == 3


@pytest.mark.asyncio
async def test_app_mounts_empty():
    """App shows empty message when no sessions."""
    from scripts.dashboard import SpendApp

    app = SpendApp(_make_empty_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        # Should show empty message, no tabs
        empty = app.query_one("#empty-message")
        assert "No sessions found" in empty.renderable


@pytest.mark.asyncio
async def test_quit_binding():
    """Pressing q should quit the app."""
    from scripts.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("q")
        # App should exit — if we get here without hang, it works


@pytest.mark.asyncio
async def test_tab_switching_keyboard():
    """Tab switching via keyboard doesn't crash."""
    from scripts.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(120, 40)) as pilot:
        # Textual TabbedContent uses tab/shift+tab or clicking
        for tab_name in ["Sessions", "Projects", "Models", "Subagents", "Costs", "Overview"]:
            await pilot.click(tab_name)
            await pilot.pause()
        # No crash = pass


@pytest.mark.asyncio
async def test_narrow_terminal():
    """App doesn't crash in a narrow terminal."""
    from scripts.dashboard import SpendApp

    app = SpendApp(_make_test_data(), "Last 7 days")
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        # No crash = pass
```

- [ ] **Step 3: Run automated TUI tests**

```bash
cd ~/code/claude-spend
python3 -m pytest tests/test_dashboard.py -v
```

Expected: All 5 tests pass. If `pytest-asyncio` is needed, add it to `requirements-dev.txt`.

**Corrective loop:** If any Pilot test fails:
1. Read the assertion error to identify *which widget/table* is wrong
2. Classify the failure:
   - **Import/instantiation error** → fix `dashboard.py` imports or `SpendApp.__init__`
   - **Widget not found (`NoMatches`)** → widget ID mismatch between test and `compose()`, or widget not yielded for the given data state — fix `compose()`
   - **Wrong row count** → data wiring issue in `_populate_*_table()` — verify the `DashboardData` fixture matches expectations, then fix the populate method
   - **Crash during tab switch** → likely a `query_one` on a widget in a hidden tab — ensure `on_mount` populates all tables regardless of active tab
   - **Test itself is wrong** → if the fixture data doesn't produce the expected counts, fix the test fixture, not the app
3. Fix `dashboard.py` (or the test if the test is wrong), then re-run `pytest tests/test_dashboard.py -v`
4. Repeat until all 5 pass. Do NOT commit until green.

- [ ] **Step 4: (Optional) Add snapshot tests**

If snapshot tests are desired for regression detection, add to `test_dashboard.py`:
```python
from pytest_textual_snapshot import snapshot_test

def test_overview_snapshot(snap_compare):
    """Snapshot of the overview tab for visual regression detection."""
    from scripts.dashboard import SpendApp
    app = SpendApp(_make_test_data(), "Last 7 days")
    assert snap_compare(app, terminal_size=(120, 40))
```

First run: `pytest --snapshot-update` to generate baseline SVGs. Subsequent runs compare against baseline.

**Note:** Snapshot tests are fragile across Textual version upgrades. Keep them in a separate test file or mark them so they can be skipped in CI if needed (`@pytest.mark.snapshot`).

- [ ] **Step 5: Commit**

```bash
cd ~/code/claude-spend
git add tests/test_dashboard.py requirements-dev.txt
git commit -m "test: add automated TUI pilot tests for widget population and edge cases"
```

---

### Task 10: Install plugin and end-to-end test

**Files:**
- No new files — testing the plugin integration

- [ ] **Step 1: Install the plugin locally**

Check how to register a local plugin. Either:
```bash
# Symlink into plugins dir
ln -s ~/code/claude-spend ~/.claude/plugins/local/claude-spend
```
Or if Claude Code uses a different mechanism, register via the CLI.

- [ ] **Step 2: Test the /spend command**

In a new Claude Code session, run `/spend 7` and verify:
- Dashboard launches
- Overview tab shows data
- All tabs are navigable
- Press `q` returns to Claude Code

- [ ] **Step 3: Test edge cases**

```bash
# No data range
cd ~/code/claude-spend/scripts && python3 dashboard.py --days 0

# All time
cd ~/code/claude-spend/scripts && python3 dashboard.py --days all
```

Expected: `--days 0` shows empty message. `--days all` shows everything.

- [ ] **Step 4: Final commit**

```bash
cd ~/code/claude-spend
git add -A
git commit -m "chore: finalize plugin for local installation"
```

---

## Summary

| Task | What it builds | Tests |
|-|-|-|
| 1 | Project scaffold, plugin manifest, /spend command | — |
| 2 | TokenUsage dataclass, cost calculation | 7 unit tests |
| 3 | Session-meta loading with time filtering | 5 unit tests |
| 4 | JSONL conversation parser (models, subagents, skills) | 5 unit tests |
| 5 | Aggregation functions (daily, project, model, subagent) | 4 unit tests |
| 6 | load_all pipeline integrating everything | 3 integration tests |
| 7 | Textual app shell with all 6 tabs + data tables | Manual checklist (9 items) |
| 8 | Plotext charts (stacked bars, bar charts) | Manual checklist (6 items) |
| 9 | Automated TUI tests (Pilot + optional Snapshot) | 5 Pilot tests + optional snapshot |
| 10 | Plugin installation and end-to-end testing | Manual E2E test |
