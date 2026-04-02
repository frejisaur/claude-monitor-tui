"""Unified QuotaState merging OAuth snapshot + hook estimates."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from claude_spend.usage_api import QuotaSnapshot
from claude_spend.hook import UsageEntry, compute_rolling_window
from claude_spend.plan_config import PlanBudget


class DataSource(Enum):
    OAUTH = "oauth"
    HOOK = "hook"
    NONE = "none"


@dataclass
class QuotaState:
    source: DataSource
    session_pct: float = 0.0
    weekly_pct: float = 0.0
    sonnet_weekly_pct: float = 0.0
    session_reset_at: datetime | None = None
    weekly_reset_at: datetime | None = None
    estimated_5h_cost: float = 0.0
    estimated_weekly_cost: float = 0.0
    budget: PlanBudget | None = None


def build_quota_state(
    oauth_snapshot: QuotaSnapshot | None,
    hook_entries: list[UsageEntry],
    budget: PlanBudget,
) -> QuotaState:
    """Build a QuotaState preferring OAuth data, falling back to hook estimates."""
    window_5h = compute_rolling_window(hook_entries, hours=5)
    window_7d = compute_rolling_window(hook_entries, hours=7 * 24)

    if oauth_snapshot is not None:
        return QuotaState(
            source=DataSource.OAUTH,
            session_pct=oauth_snapshot.session_pct,
            weekly_pct=oauth_snapshot.weekly_pct,
            sonnet_weekly_pct=oauth_snapshot.weekly_sonnet_pct,
            session_reset_at=oauth_snapshot.session_reset_at,
            weekly_reset_at=oauth_snapshot.weekly_reset_at,
            estimated_5h_cost=window_5h.total_cost,
            estimated_weekly_cost=window_7d.total_cost,
            budget=budget,
        )

    if hook_entries:
        session_pct = min(1.0, window_5h.total_cost / budget.five_hour_budget) if budget.five_hour_budget > 0 else 0.0
        weekly_pct = min(1.0, window_7d.total_cost / budget.weekly_budget) if budget.weekly_budget > 0 else 0.0
        return QuotaState(
            source=DataSource.HOOK,
            session_pct=session_pct,
            weekly_pct=weekly_pct,
            sonnet_weekly_pct=0.0,
            estimated_5h_cost=window_5h.total_cost,
            estimated_weekly_cost=window_7d.total_cost,
            budget=budget,
        )

    return QuotaState(source=DataSource.NONE, budget=budget)
