"""Tests for claude_spend/hook.py — Stop hook data layer."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

import pytest

from claude_spend.hook import (
    UsageEntry,
    WindowSummary,
    SessionContribution,
    extract_latest_usage,
    append_usage_entry,
    load_usage_log,
    compute_rolling_window,
    compute_session_contributions,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_jsonl_path(tmp_path):
    """Create a JSONL with two assistant messages: msg_001 and msg_002."""
    p = tmp_path / "session.jsonl"
    messages = [
        {
            "type": "assistant",
            "uuid": "msg_001",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        },
        {
            "type": "assistant",
            "uuid": "msg_002",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 2000,
                    "output_tokens": 400,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 800,
                },
            },
        },
    ]
    with open(p, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return str(p)


# ---------------------------------------------------------------------------
# TestExtractLatestUsage
# ---------------------------------------------------------------------------

class TestExtractLatestUsage:
    def test_extracts_last_message(self, sample_jsonl_path):
        entry = extract_latest_usage(sample_jsonl_path, session_id="sess-abc")
        assert entry is not None
        assert entry.message_id == "msg_002"
        assert entry.input_tokens == 2000
        assert entry.output_tokens == 400
        assert entry.cache_write_tokens == 500
        assert entry.cache_read_tokens == 800

    def test_missing_file_returns_none(self, tmp_path):
        path = str(tmp_path / "nonexistent.jsonl")
        result = extract_latest_usage(path, session_id="sess-x")
        assert result is None

    def test_empty_file_returns_none(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        result = extract_latest_usage(str(p), session_id="sess-x")
        assert result is None

    def test_positive_cost(self, sample_jsonl_path):
        entry = extract_latest_usage(sample_jsonl_path, session_id="sess-abc")
        assert entry is not None
        assert entry.estimated_cost > 0.0


# ---------------------------------------------------------------------------
# TestAppendAndDedup
# ---------------------------------------------------------------------------

class TestAppendAndDedup:
    def _make_entry(self, session_id="sess-1", message_id="msg-a", cost=0.01):
        return UsageEntry(
            ts=datetime.now(timezone.utc),
            session_id=session_id,
            message_id=message_id,
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            cache_write_tokens=0,
            cache_read_tokens=0,
            estimated_cost=cost,
            project="test-proj",
        )

    def test_creates_file_on_first_append(self, tmp_path):
        log = str(tmp_path / "usage-log.jsonl")
        entry = self._make_entry()
        append_usage_entry(log, entry)
        assert os.path.isfile(log)
        with open(log) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1

    def test_additive_entries(self, tmp_path):
        log = str(tmp_path / "usage-log.jsonl")
        append_usage_entry(log, self._make_entry(message_id="msg-a"))
        append_usage_entry(log, self._make_entry(message_id="msg-b"))
        with open(log) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2

    def test_dedup_skips_duplicate(self, tmp_path):
        log = str(tmp_path / "usage-log.jsonl")
        entry = self._make_entry(message_id="msg-a")
        append_usage_entry(log, entry)
        append_usage_entry(log, entry)  # duplicate — should be skipped
        with open(log) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# TestRollingWindows
# ---------------------------------------------------------------------------

class TestRollingWindows:
    def _entries(self, now):
        """Three entries: 0.5h ago, 6h ago, 10d ago."""
        return [
            UsageEntry(
                ts=now - timedelta(hours=0.5),
                session_id="s1", message_id="m1", model="claude-sonnet-4-6",
                input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
                estimated_cost=0.10, project="p1",
            ),
            UsageEntry(
                ts=now - timedelta(hours=6),
                session_id="s1", message_id="m2", model="claude-sonnet-4-6",
                input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
                estimated_cost=0.20, project="p1",
            ),
            UsageEntry(
                ts=now - timedelta(days=10),
                session_id="s2", message_id="m3", model="claude-sonnet-4-6",
                input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
                estimated_cost=0.30, project="p2",
            ),
        ]

    def test_5h_window(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entries = self._entries(now)
        summary = compute_rolling_window(entries, hours=5, now=now)
        # Only the 0.5h entry falls within the strict 5h window
        assert summary.entry_count == 1
        assert abs(summary.total_cost - 0.10) < 1e-9

    def test_7d_window(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entries = self._entries(now)
        summary = compute_rolling_window(entries, hours=7 * 24, now=now)
        # The 0.5h and 6h entries fall within 7 days; the 10d entry does not
        assert summary.entry_count == 2
        assert abs(summary.total_cost - 0.30) < 1e-9

    def test_empty_entries(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        summary = compute_rolling_window([], hours=5, now=now)
        assert summary.entry_count == 0
        assert summary.total_cost == 0.0


# ---------------------------------------------------------------------------
# TestSessionContributions
# ---------------------------------------------------------------------------

class TestSessionContributions:
    def test_contributions_sum_to_window_total(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entries = [
            UsageEntry(
                ts=now - timedelta(hours=1),
                session_id="s1", message_id="m1", model="claude-sonnet-4-6",
                input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
                estimated_cost=0.30, project="p1",
            ),
            UsageEntry(
                ts=now - timedelta(hours=2),
                session_id="s2", message_id="m2", model="claude-sonnet-4-6",
                input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
                estimated_cost=0.70, project="p2",
            ),
        ]
        contribs = compute_session_contributions(entries, hours=5, now=now)
        total_pct = sum(c.pct for c in contribs)
        assert abs(total_pct - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# TestLogRotation
# ---------------------------------------------------------------------------

class TestLogRotation:
    def _old_entry(self, days_ago=100):
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return UsageEntry(
            ts=ts,
            session_id="old-sess", message_id="old-msg", model="claude-sonnet-4-6",
            input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
            estimated_cost=0.01, project="proj",
        )

    def _fresh_entry(self):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        return UsageEntry(
            ts=ts,
            session_id="new-sess", message_id="new-msg", model="claude-sonnet-4-6",
            input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
            estimated_cost=0.01, project="proj",
        )

    def test_prune_removes_stale_entries(self, tmp_path):
        log = str(tmp_path / "usage-log.jsonl")
        append_usage_entry(log, self._old_entry(days_ago=100))
        append_usage_entry(log, self._fresh_entry())
        entries = load_usage_log(log, prune=True)
        assert all(e.session_id != "old-sess" for e in entries)
        assert any(e.session_id == "new-sess" for e in entries)

    def test_no_prune_keeps_file_intact(self, tmp_path):
        log = str(tmp_path / "usage-log.jsonl")
        append_usage_entry(log, self._old_entry(days_ago=100))
        append_usage_entry(log, self._fresh_entry())
        entries = load_usage_log(log, prune=False)
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# TestHookMain
# ---------------------------------------------------------------------------

class TestHookMain:
    def test_main_processes_stdin(self, sample_jsonl_path, tmp_path, monkeypatch):
        import io
        from claude_spend import hook

        log_path = str(tmp_path / "usage-log.jsonl")
        monkeypatch.setattr(hook, "_get_log_path", lambda: log_path)

        stdin_data = json.dumps({
            "session_id": "test-sess",
            "transcript_path": sample_jsonl_path,
            "project_path": "/tmp/test-project",
        })
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin_data))

        hook.main()

        entries = load_usage_log(log_path, prune=False)
        assert len(entries) == 1
        assert entries[0].session_id == "test-sess"

    def test_main_handles_empty_stdin(self, tmp_path, monkeypatch):
        import io
        from claude_spend import hook

        log_path = str(tmp_path / "usage-log.jsonl")
        monkeypatch.setattr(hook, "_get_log_path", lambda: log_path)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))

        # Should not raise
        hook.main()

        assert not os.path.isfile(log_path)
