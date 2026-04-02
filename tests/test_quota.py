"""Tests for unified QuotaState that merges OAuth + hook data."""

from datetime import datetime, timezone, timedelta
import pytest

from claude_spend.quota import QuotaState, build_quota_state, DataSource
from claude_spend.usage_api import QuotaSnapshot
from claude_spend.hook import UsageEntry
from claude_spend.plan_config import PlanBudget, PLAN_BUDGETS


class TestBuildQuotaState:
    def test_oauth_takes_priority(self):
        snap = QuotaSnapshot(
            session_pct=0.78, weekly_pct=0.42, weekly_sonnet_pct=0.18,
            session_reset_at=datetime(2026, 4, 1, 16, 0, tzinfo=timezone.utc),
            weekly_reset_at=datetime(2026, 4, 5, 8, 0, tzinfo=timezone.utc),
            weekly_sonnet_reset_at=None,
        )
        now = datetime.now(timezone.utc)
        hook_entries = [
            UsageEntry(ts=now, session_id="s1", message_id="m1", model="claude-opus-4-6",
                       input_tokens=1000, output_tokens=200, cache_write_tokens=0,
                       cache_read_tokens=0, estimated_cost=2.00, project="test"),
        ]
        budget = PLAN_BUDGETS["max5"]
        state = build_quota_state(oauth_snapshot=snap, hook_entries=hook_entries, budget=budget)
        assert state.source == DataSource.OAUTH
        assert state.session_pct == pytest.approx(0.78)
        assert state.weekly_pct == pytest.approx(0.42)
        assert state.session_reset_at is not None

    def test_hook_fallback_when_no_oauth(self):
        now = datetime.now(timezone.utc)
        entries = [
            UsageEntry(ts=now - timedelta(hours=1), session_id="s1", message_id="m1",
                       model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                       cache_write_tokens=0, cache_read_tokens=0,
                       estimated_cost=4.40, project="test"),
        ]
        budget = PLAN_BUDGETS["max5"]  # 5h budget = $8.80
        state = build_quota_state(oauth_snapshot=None, hook_entries=entries, budget=budget)
        assert state.source == DataSource.HOOK
        assert state.session_pct == pytest.approx(4.40 / 8.80, abs=0.01)
        assert state.session_reset_at is None

    def test_no_data_returns_empty_state(self):
        budget = PLAN_BUDGETS["pro"]
        state = build_quota_state(oauth_snapshot=None, hook_entries=[], budget=budget)
        assert state.source == DataSource.NONE
        assert state.session_pct == 0.0
        assert state.weekly_pct == 0.0

    def test_hook_estimated_cost_used(self):
        now = datetime.now(timezone.utc)
        entries = [
            UsageEntry(ts=now - timedelta(hours=1), session_id="s1", message_id="m1",
                       model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                       cache_write_tokens=0, cache_read_tokens=0,
                       estimated_cost=3.00, project="test"),
            UsageEntry(ts=now - timedelta(days=2), session_id="s2", message_id="m2",
                       model="claude-opus-4-6", input_tokens=1000, output_tokens=200,
                       cache_write_tokens=0, cache_read_tokens=0,
                       estimated_cost=7.00, project="test"),
        ]
        budget = PlanBudget(name="Test", five_hour_budget=10.0, weekly_budget=100.0, monthly_price=0)
        state = build_quota_state(oauth_snapshot=None, hook_entries=entries, budget=budget)
        # 5h: only s1 ($3.00) → 3/10 = 0.30
        assert state.session_pct == pytest.approx(0.30, abs=0.01)
        assert state.estimated_5h_cost == pytest.approx(3.00, abs=0.01)
        # 7d: s1 + s2 ($10.00) → 10/100 = 0.10
        assert state.weekly_pct == pytest.approx(0.10, abs=0.01)
        assert state.estimated_weekly_cost == pytest.approx(10.00, abs=0.01)
