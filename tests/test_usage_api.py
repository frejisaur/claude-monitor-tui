"""Tests for claude_spend/usage_api.py"""
import json
import time
import warnings
from pathlib import Path

import pytest

from claude_spend.usage_api import (
    CACHE_TTL_SECONDS,
    QuotaSnapshot,
    _parse_api_response,
    load_cached_snapshot,
    load_credentials_token,
    save_cached_snapshot,
)

MOCK_API_RESPONSE = {
    "session": {"used_percent": 0.78, "reset_at": "2026-04-01T16:14:00Z"},
    "weekly": {"used_percent": 0.42, "reset_at": "2026-04-05T08:00:00Z"},
    "weekly_sonnet": {"used_percent": 0.18, "reset_at": "2026-04-05T08:00:00Z"},
}


class TestParseApiResponse:
    def test_parses_valid_response(self):
        snap = _parse_api_response(MOCK_API_RESPONSE)
        assert snap is not None
        assert snap.session_pct == pytest.approx(0.78)
        assert snap.weekly_pct == pytest.approx(0.42)
        assert snap.weekly_sonnet_pct == pytest.approx(0.18)
        assert snap.session_reset_at is not None
        assert snap.weekly_reset_at is not None

    def test_handles_missing_fields_gracefully(self):
        partial = {"session": {"used_percent": 0.5}}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            snap = _parse_api_response(partial)
        # No warning because session key is present
        assert snap is not None
        assert snap.session_pct == pytest.approx(0.5)
        assert snap.weekly_pct == pytest.approx(0.0)
        assert snap.weekly_sonnet_pct == pytest.approx(0.0)
        assert snap.weekly_reset_at is None
        assert snap.session_reset_at is None

    def test_emits_warning_for_missing_session_key(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            snap = _parse_api_response({"weekly": {"used_percent": 0.3}})
        assert any(issubclass(warning.category, UserWarning) for warning in w)


class TestCredentials:
    def test_loads_token_from_file(self, tmp_path):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "sk-test-token-123"}})
        )
        token = load_credentials_token(str(creds_file))
        assert token == "sk-test-token-123"

    def test_returns_none_for_missing_file(self, tmp_path):
        token = load_credentials_token(str(tmp_path / "nonexistent.json"))
        assert token is None

    def test_returns_none_for_malformed_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{bad json")
        token = load_credentials_token(str(bad_file))
        assert token is None

    def test_returns_none_for_missing_key_path(self, tmp_path):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({"other": "data"}))
        token = load_credentials_token(str(creds_file))
        assert token is None


class TestCaching:
    def test_save_and_load_cache(self, tmp_path):
        cache_file = tmp_path / "quota-cache.json"
        snap = QuotaSnapshot(
            session_pct=0.78,
            weekly_pct=0.42,
            weekly_sonnet_pct=0.18,
            session_reset_at=None,
            weekly_reset_at=None,
            weekly_sonnet_reset_at=None,
        )
        save_cached_snapshot(snap, str(cache_file))
        loaded = load_cached_snapshot(str(cache_file))
        assert loaded is not None
        assert loaded.session_pct == pytest.approx(0.78)

    def test_expired_cache_returns_none(self, tmp_path):
        cache_file = tmp_path / "quota-cache.json"
        snap = QuotaSnapshot(
            session_pct=0.5,
            weekly_pct=0.0,
            weekly_sonnet_pct=0.0,
            session_reset_at=None,
            weekly_reset_at=None,
            weekly_sonnet_reset_at=None,
        )
        save_cached_snapshot(snap, str(cache_file))
        # Backdate cached_at beyond TTL
        data = json.loads(cache_file.read_text())
        data["cached_at"] = time.time() - CACHE_TTL_SECONDS - 1
        cache_file.write_text(json.dumps(data))
        result = load_cached_snapshot(str(cache_file))
        assert result is None

    def test_missing_cache_returns_none(self, tmp_path):
        result = load_cached_snapshot(str(tmp_path / "nonexistent.json"))
        assert result is None
