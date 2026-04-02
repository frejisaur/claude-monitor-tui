"""Stop hook: extract usage from session JSONL, log to ~/.claude-spend/usage-log.jsonl."""

from __future__ import annotations

import json
import os
import sys
import fcntl
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta

from claude_spend.data import PRICING, FALLBACK_MODEL, calculate_cost, TokenUsage


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

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
    pct: float


# ---------------------------------------------------------------------------
# Extract from session JSONL
# ---------------------------------------------------------------------------

def extract_latest_usage(jsonl_path: str, session_id: str) -> UsageEntry | None:
    """Read a session JSONL, find the last assistant message with usage, return UsageEntry."""
    if not os.path.isfile(jsonl_path):
        return None

    last_entry: UsageEntry | None = None

    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") != "assistant":
                    continue

                inner = msg.get("message", {})
                usage_raw = inner.get("usage")
                if not usage_raw:
                    continue

                model = inner.get("model") or FALLBACK_MODEL
                message_id = msg.get("uuid", "")

                usage = TokenUsage(
                    input_tokens=usage_raw.get("input_tokens", 0),
                    output_tokens=usage_raw.get("output_tokens", 0),
                    cache_write_tokens=usage_raw.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
                )
                cost = calculate_cost(usage, model)

                last_entry = UsageEntry(
                    ts=datetime.now(timezone.utc),
                    session_id=session_id,
                    message_id=message_id,
                    model=model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    estimated_cost=cost,
                    project="",
                )
    except OSError:
        return None

    return last_entry


# ---------------------------------------------------------------------------
# Dedup key
# ---------------------------------------------------------------------------

def _entry_dedup_key(entry: UsageEntry) -> str:
    return f"{entry.session_id}:{entry.message_id}"


# ---------------------------------------------------------------------------
# Log constants and path
# ---------------------------------------------------------------------------

LOG_RETENTION_DAYS = 90


def _get_log_path() -> str:
    """Return the default log path ~/.claude-spend/usage-log.jsonl."""
    return os.path.expanduser("~/.claude-spend/usage-log.jsonl")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _entry_to_dict(entry: UsageEntry) -> dict:
    d = asdict(entry)
    d["ts"] = entry.ts.isoformat()
    return d


def _entry_from_dict(d: dict) -> UsageEntry:
    ts_raw = d.get("ts", "")
    try:
        ts = datetime.fromisoformat(ts_raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc)
    return UsageEntry(
        ts=ts,
        session_id=d.get("session_id", ""),
        message_id=d.get("message_id", ""),
        model=d.get("model", FALLBACK_MODEL),
        input_tokens=d.get("input_tokens", 0),
        output_tokens=d.get("output_tokens", 0),
        cache_write_tokens=d.get("cache_write_tokens", 0),
        cache_read_tokens=d.get("cache_read_tokens", 0),
        estimated_cost=d.get("estimated_cost", 0.0),
        project=d.get("project", ""),
    )


# ---------------------------------------------------------------------------
# Load usage log with rotation
# ---------------------------------------------------------------------------

def load_usage_log(log_path: str, prune: bool = True) -> list[UsageEntry]:
    """Load JSONL log, filter entries older than 90 days, optionally rewrite file."""
    if not os.path.isfile(log_path):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)
    all_entries: list[UsageEntry] = []
    stale_found = False

    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    entry = _entry_from_dict(d)
                    all_entries.append(entry)
                    if entry.ts < cutoff:
                        stale_found = True
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        return []

    fresh_entries = [e for e in all_entries if e.ts >= cutoff]

    if not prune:
        return all_entries

    entries = fresh_entries

    if stale_found:
        try:
            with open(log_path, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    for entry in entries:
                        f.write(json.dumps(_entry_to_dict(entry)) + "\n")
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            pass

    return entries


# ---------------------------------------------------------------------------
# Tail dedup
# ---------------------------------------------------------------------------

def _tail_dedup_keys(log_path: str, n: int = 50) -> set[str]:
    """Read last ~10KB of log_path, parse last N lines, return dedup keys."""
    keys: set[str] = set()
    if not os.path.isfile(log_path):
        return keys

    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            seek_pos = max(0, size - 10240)
            f.seek(seek_pos)
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return keys

    lines = chunk.splitlines()
    # If we sought into the middle of a line, discard the first partial line
    if seek_pos > 0 and lines:
        lines = lines[1:]

    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            entry = _entry_from_dict(d)
            keys.add(_entry_dedup_key(entry))
        except (json.JSONDecodeError, KeyError):
            continue

    return keys


# ---------------------------------------------------------------------------
# Append entry with locking and tail dedup
# ---------------------------------------------------------------------------

def append_usage_entry(log_path: str, entry: UsageEntry) -> None:
    """Append a UsageEntry to log_path, with tail-dedup and fcntl locking."""
    # Ensure directory exists
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    key = _entry_dedup_key(entry)
    existing_keys = _tail_dedup_keys(log_path)
    if key in existing_keys:
        return

    try:
        with open(log_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(_entry_to_dict(entry)) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        _log_error(f"append_usage_entry failed: {e}")


# ---------------------------------------------------------------------------
# Rolling window computation
# ---------------------------------------------------------------------------

def compute_rolling_window(
    entries: list[UsageEntry],
    hours: float,
    now: datetime | None = None,
) -> WindowSummary:
    """Return WindowSummary for entries strictly within the last `hours` hours.

    Uses strict `>` boundary: entry.ts > (now - hours).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    in_window = [e for e in entries if e.ts > cutoff]
    total_cost = sum(e.estimated_cost for e in in_window)
    return WindowSummary(
        total_cost=total_cost,
        entry_count=len(in_window),
        entries=in_window,
    )


# ---------------------------------------------------------------------------
# Session contributions
# ---------------------------------------------------------------------------

def compute_session_contributions(
    entries: list[UsageEntry],
    hours: float,
    now: datetime | None = None,
) -> list[SessionContribution]:
    """Group entries within window by session_id, compute cost and percentage."""
    summary = compute_rolling_window(entries, hours=hours, now=now)
    if not summary.entries:
        return []

    by_session: dict[str, list[UsageEntry]] = {}
    for e in summary.entries:
        by_session.setdefault(e.session_id, []).append(e)

    total = summary.total_cost
    contributions: list[SessionContribution] = []
    for session_id, sess_entries in by_session.items():
        cost = sum(e.estimated_cost for e in sess_entries)
        pct = cost / total if total > 0 else 0.0
        project = sess_entries[0].project
        contributions.append(SessionContribution(
            session_id=session_id,
            project=project,
            cost=cost,
            pct=pct,
        ))

    contributions.sort(key=lambda c: c.cost, reverse=True)
    return contributions


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

def _log_error(msg: str) -> None:
    """Append an error message to ~/.claude-spend/hook.log."""
    log_dir = os.path.expanduser("~/.claude-spend")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "hook.log")
        ts = datetime.now(timezone.utc).isoformat()
        with open(log_path, "a") as f:
            f.write(f"{ts} ERROR: {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main stdin entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Read JSON from stdin, extract usage, append to log."""
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        _log_error(f"main: failed to read stdin: {e}")
        return

    session_id = data.get("session_id", "")
    transcript_path = data.get("transcript_path", "")
    project_path = data.get("project_path", "")
    project = os.path.basename(project_path.rstrip("/")) if project_path else ""

    if not transcript_path:
        _log_error("main: no transcript_path in stdin JSON")
        return

    entry = extract_latest_usage(transcript_path, session_id=session_id)
    if entry is None:
        return

    entry.project = project

    log_path = _get_log_path()
    append_usage_entry(log_path, entry)


if __name__ == "__main__":
    main()
