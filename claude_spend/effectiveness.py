"""Effectiveness data: facet loading, proxy heuristic, and aggregation."""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field


@dataclass
class SessionFacet:
    session_id: str = ""
    underlying_goal: str = ""
    goal_categories: dict[str, int] = field(default_factory=dict)
    outcome: str = ""
    session_type: str = ""
    claude_helpfulness: str = ""
    friction_counts: dict[str, int] = field(default_factory=dict)
    friction_detail: str = ""
    primary_success: str = ""
    brief_summary: str = ""


def load_facets(claude_dir: str) -> dict[str, SessionFacet]:
    """Load facet files from usage-data/facets/. Returns dict keyed by session_id."""
    facets_dir = os.path.join(claude_dir, "usage-data", "facets")
    if not os.path.isdir(facets_dir):
        return {}

    result: dict[str, SessionFacet] = {}
    for path in glob.glob(os.path.join(facets_dir, "*.json")):
        try:
            with open(path) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        sid = raw.get("session_id", "")
        if not sid:
            sid = os.path.basename(path).removesuffix(".json")

        result[sid] = SessionFacet(
            session_id=sid,
            underlying_goal=raw.get("underlying_goal", ""),
            goal_categories=raw.get("goal_categories", {}),
            outcome=raw.get("outcome", ""),
            session_type=raw.get("session_type", ""),
            claude_helpfulness=raw.get("claude_helpfulness", ""),
            friction_counts=raw.get("friction_counts", {}),
            friction_detail=raw.get("friction_detail", ""),
            primary_success=raw.get("primary_success", ""),
            brief_summary=raw.get("brief_summary", ""),
        )

    return result


from claude_spend.data import SessionMeta, SessionSummary


@dataclass
class SessionEffectiveness:
    session_id: str = ""
    outcome: str = ""
    outcome_source: str = ""  # "facet" or "proxy"
    goal_categories: dict[str, int] = field(default_factory=dict)
    efficiency_score: float = 0.0
    friction_counts: dict[str, int] = field(default_factory=dict)


ACHIEVED_OUTCOMES = {"fully_achieved", "mostly_achieved", "likely_achieved"}


def compute_proxy_outcome(meta: SessionMeta, median_duration: int) -> str:
    """Estimate session outcome from quantitative signals when no facet exists.

    Scoring:
      +2 if has git commits
      +2 if tool error rate < 10%
      +1 if no user interruptions
      +1 if duration < 2x median

    Returns: "likely_achieved" (>=4), "unclear" (2-3), "likely_not_achieved" (<2)
    """
    score = 0

    if meta.git_commits > 0:
        score += 2

    total_tool_uses = sum(meta.tool_counts.values()) if meta.tool_counts else 0
    error_rate = meta.tool_errors / max(1, total_tool_uses)
    if error_rate < 0.10:
        score += 2

    if meta.user_interruptions == 0:
        score += 1

    if median_duration > 0 and meta.duration_minutes < 2 * median_duration:
        score += 1

    if score >= 4:
        return "likely_achieved"
    elif score >= 2:
        return "unclear"
    else:
        return "likely_not_achieved"


def build_session_effectiveness(
    session: SessionSummary,
    meta: SessionMeta,
    facet: SessionFacet | None,
    category_avg_costs: dict[str, float],
    median_duration: int = 30,
) -> SessionEffectiveness:
    """Build effectiveness record for a single session."""
    if facet and facet.outcome:
        outcome = facet.outcome
        source = "facet"
        categories = facet.goal_categories
        friction = facet.friction_counts
    else:
        outcome = compute_proxy_outcome(meta, median_duration)
        source = "proxy"
        categories = {}
        friction = {}

    # Efficiency score: session cost / avg cost for its primary category
    primary_cat = max(categories, key=categories.get) if categories else None
    if primary_cat and primary_cat in category_avg_costs and category_avg_costs[primary_cat] > 0:
        efficiency = session.estimated_cost / category_avg_costs[primary_cat]
    else:
        efficiency = 0.0

    return SessionEffectiveness(
        session_id=session.session_id,
        outcome=outcome,
        outcome_source=source,
        goal_categories=categories,
        efficiency_score=efficiency,
        friction_counts=friction,
    )
