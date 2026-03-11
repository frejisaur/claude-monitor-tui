import json
from datetime import datetime, timezone, timedelta
from claude_spend.data import load_session_metas, SessionMeta, parse_conversation_jsonl, ConversationData


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
