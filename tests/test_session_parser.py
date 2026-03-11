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
