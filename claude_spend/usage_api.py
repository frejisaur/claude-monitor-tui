"""OAuth usage API client for Anthropic Claude quota information.

This module queries an undocumented API endpoint to retrieve quota usage
percentages for the current session and weekly windows. The response schema
is community-discovered and may change without notice.
"""
from __future__ import annotations

import json
import os
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"
CACHE_TTL_SECONDS = 60
DEFAULT_CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
DEFAULT_CACHE_PATH = os.path.expanduser("~/.claude-spend/quota-cache.json")


@dataclass
class QuotaSnapshot:
    session_pct: float
    weekly_pct: float
    weekly_sonnet_pct: float
    session_reset_at: Optional[datetime]
    weekly_reset_at: Optional[datetime]
    weekly_sonnet_reset_at: Optional[datetime]


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string, handling Z suffix."""
    if not s:
        return None
    try:
        normalized = s.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, AttributeError):
        return None


def _parse_api_response(data: dict) -> Optional[QuotaSnapshot]:
    """Parse raw API response dict into a QuotaSnapshot.

    Emits a UserWarning if the expected 'session' key is missing, as this
    may indicate a schema change.
    """
    if "session" not in data:
        warnings.warn(
            "Usage API response missing 'session' key — schema may have changed",
            UserWarning,
            stacklevel=2,
        )

    session = data.get("session") or {}
    weekly = data.get("weekly") or {}
    weekly_sonnet = data.get("weekly_sonnet") or {}

    return QuotaSnapshot(
        session_pct=float(session.get("used_percent", 0.0)),
        weekly_pct=float(weekly.get("used_percent", 0.0)),
        weekly_sonnet_pct=float(weekly_sonnet.get("used_percent", 0.0)),
        session_reset_at=_parse_iso(session.get("reset_at")),
        weekly_reset_at=_parse_iso(weekly.get("reset_at")),
        weekly_sonnet_reset_at=_parse_iso(weekly_sonnet.get("reset_at")),
    )


def load_credentials_token(
    path: str = DEFAULT_CREDENTIALS_PATH,
) -> Optional[str]:
    """Load the OAuth access token from the credentials file.

    Returns None on any error (missing file, bad JSON, missing key path).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["claudeAiOauth"]["accessToken"]
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    except Exception:
        return None


def save_cached_snapshot(
    snapshot: QuotaSnapshot,
    path: str = DEFAULT_CACHE_PATH,
) -> None:
    """Persist a QuotaSnapshot to disk as JSON with a timestamp."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt is not None else None

    payload = {
        "cached_at": time.time(),
        "session_pct": snapshot.session_pct,
        "weekly_pct": snapshot.weekly_pct,
        "weekly_sonnet_pct": snapshot.weekly_sonnet_pct,
        "session_reset_at": _dt_to_str(snapshot.session_reset_at),
        "weekly_reset_at": _dt_to_str(snapshot.weekly_reset_at),
        "weekly_sonnet_reset_at": _dt_to_str(snapshot.weekly_sonnet_reset_at),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def load_cached_snapshot(
    path: str = DEFAULT_CACHE_PATH,
) -> Optional[QuotaSnapshot]:
    """Load a cached QuotaSnapshot, returning None if missing or expired."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", 0.0)
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            return None
        return QuotaSnapshot(
            session_pct=float(data.get("session_pct", 0.0)),
            weekly_pct=float(data.get("weekly_pct", 0.0)),
            weekly_sonnet_pct=float(data.get("weekly_sonnet_pct", 0.0)),
            session_reset_at=_parse_iso(data.get("session_reset_at")),
            weekly_reset_at=_parse_iso(data.get("weekly_reset_at")),
            weekly_sonnet_reset_at=_parse_iso(data.get("weekly_sonnet_reset_at")),
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None


def fetch_quota_snapshot(
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
    cache_path: str = DEFAULT_CACHE_PATH,
) -> Optional[QuotaSnapshot]:
    """Fetch quota usage, using cached data when fresh.

    Order of operations:
    1. Return cached snapshot if within TTL.
    2. Load OAuth token from credentials file.
    3. Perform HTTP GET with 5s timeout.
    4. Parse and cache the response.

    Returns None on any failure — never raises.
    """
    cached = load_cached_snapshot(cache_path)
    if cached is not None:
        return cached

    token = load_credentials_token(credentials_path)
    if token is None:
        return None

    try:
        req = Request(
            USAGE_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": BETA_HEADER,
            },
        )
        with urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        snapshot = _parse_api_response(raw)
        if snapshot is not None:
            save_cached_snapshot(snapshot, cache_path)
        return snapshot
    except (URLError, json.JSONDecodeError, Exception):
        return None
