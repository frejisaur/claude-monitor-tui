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
