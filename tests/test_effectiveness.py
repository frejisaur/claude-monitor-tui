import json
import os
import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture
def sample_facet():
    return {
        "session_id": "abc-123",
        "underlying_goal": "Fix authentication bug",
        "goal_categories": {"debugging_investigation": 1, "implementation": 1},
        "outcome": "fully_achieved",
        "session_type": "iterative_refinement",
        "claude_helpfulness": "very_helpful",
        "friction_counts": {"tool_permission_error": 1},
        "friction_detail": "User had to approve tool access",
        "primary_success": "multi_file_changes",
        "brief_summary": "Fixed auth bug across multiple files",
    }


def test_load_facets(tmp_claude_dir, sample_facet):
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "abc-123.json", "w") as f:
        json.dump(sample_facet, f)

    from claude_spend.effectiveness import load_facets
    result = load_facets(str(tmp_claude_dir))
    assert "abc-123" in result
    facet = result["abc-123"]
    assert facet.outcome == "fully_achieved"
    assert facet.goal_categories == {"debugging_investigation": 1, "implementation": 1}
    assert facet.friction_counts == {"tool_permission_error": 1}
    assert facet.brief_summary == "Fixed auth bug across multiple files"


def test_load_facets_missing_dir(tmp_claude_dir):
    from claude_spend.effectiveness import load_facets
    result = load_facets(str(tmp_claude_dir))
    assert result == {}


def test_load_facets_invalid_json(tmp_claude_dir):
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "bad.json", "w") as f:
        f.write("not json")

    from claude_spend.effectiveness import load_facets
    result = load_facets(str(tmp_claude_dir))
    assert result == {}


def test_proxy_score_high(tmp_claude_dir):
    """Session with commits, no errors, no interruptions -> likely_achieved."""
    from claude_spend.data import SessionMeta
    from claude_spend.effectiveness import compute_proxy_outcome

    meta = SessionMeta(
        session_id="s1",
        git_commits=3,
        tool_errors=0,
        user_interruptions=0,
        duration_minutes=20,
    )
    result = compute_proxy_outcome(meta, median_duration=30)
    assert result == "likely_achieved"


def test_proxy_score_low(tmp_claude_dir):
    """Session with no commits, errors, interruptions -> likely_not_achieved."""
    from claude_spend.data import SessionMeta
    from claude_spend.effectiveness import compute_proxy_outcome

    meta = SessionMeta(
        session_id="s2",
        git_commits=0,
        tool_errors=5,
        user_interruptions=3,
        duration_minutes=90,
    )
    result = compute_proxy_outcome(meta, median_duration=30)
    assert result == "likely_not_achieved"


def test_proxy_score_mid(tmp_claude_dir):
    """Session with commits but also errors and long duration -> unclear."""
    from claude_spend.data import SessionMeta
    from claude_spend.effectiveness import compute_proxy_outcome

    meta = SessionMeta(
        session_id="s3",
        git_commits=1,
        tool_errors=8,
        user_interruptions=0,
        duration_minutes=70,  # > 2*30 median, so no duration bonus
        tool_counts={"Bash": 10, "Read": 5},
    )
    # score: +2 commits, +0 error_rate(53%), +1 no interrupts, +0 long duration = 3 -> unclear
    result = compute_proxy_outcome(meta, median_duration=30)
    assert result == "unclear"


def test_build_effectiveness_with_facet():
    from claude_spend.data import SessionMeta, SessionSummary, TokenUsage
    from claude_spend.effectiveness import SessionFacet, build_session_effectiveness

    facet = SessionFacet(
        session_id="s1",
        outcome="fully_achieved",
        goal_categories={"implementation": 1},
        friction_counts={"tool_permission_error": 2},
    )
    session = SessionSummary(
        session_id="s1",
        estimated_cost=3.50,
    )
    meta = SessionMeta(session_id="s1")

    result = build_session_effectiveness(
        session=session, meta=meta, facet=facet, category_avg_costs={"implementation": 4.00},
    )
    assert result.outcome == "fully_achieved"
    assert result.outcome_source == "facet"
    assert result.efficiency_score == pytest.approx(3.50 / 4.00)
    assert result.friction_counts == {"tool_permission_error": 2}


def test_aggregate_effectiveness():
    from claude_spend.data import SessionSummary, SessionMeta
    from claude_spend.effectiveness import (
        SessionEffectiveness, EffectivenessAggregates, aggregate_effectiveness,
    )

    records = [
        SessionEffectiveness(session_id="s1", outcome="fully_achieved", outcome_source="facet",
                             goal_categories={"implementation": 1}, efficiency_score=0.8,
                             friction_counts={"tool_permission_error": 1}),
        SessionEffectiveness(session_id="s2", outcome="mostly_achieved", outcome_source="proxy",
                             goal_categories={"debugging": 1}, efficiency_score=1.2,
                             friction_counts={}),
        SessionEffectiveness(session_id="s3", outcome="not_achieved", outcome_source="facet",
                             goal_categories={"implementation": 1}, efficiency_score=2.0,
                             friction_counts={"wrong_approach": 1, "tool_permission_error": 1}),
    ]
    sessions_by_id = {
        "s1": SessionSummary(session_id="s1", estimated_cost=3.00, duration_minutes=20),
        "s2": SessionSummary(session_id="s2", estimated_cost=2.00, duration_minutes=15),
        "s3": SessionSummary(session_id="s3", estimated_cost=7.00, duration_minutes=40),
    }
    metas_by_id = {
        "s1": SessionMeta(session_id="s1", duration_minutes=20),
        "s2": SessionMeta(session_id="s2", duration_minutes=15),
        "s3": SessionMeta(session_id="s3", duration_minutes=40),
    }

    agg = aggregate_effectiveness(records, sessions_by_id, metas_by_id)
    assert agg.total_sessions == 3
    assert agg.faceted_count == 2
    assert agg.proxied_count == 1
    # 2 of 3 are achieved (fully + mostly)
    assert agg.achievement_rate == pytest.approx(2 / 3)
    assert agg.avg_efficiency == pytest.approx((0.8 + 1.2 + 2.0) / 3)
    # friction: tool_permission_error=2, wrong_approach=1
    assert agg.friction_totals["tool_permission_error"] == 2
    assert agg.friction_totals["wrong_approach"] == 1
    # friction avg extra cost should be populated
    assert "tool_permission_error" in agg.friction_avg_extra_cost
    # category breakdown
    assert "implementation" in agg.category_stats
    assert agg.category_stats["implementation"]["sessions"] == 2
    assert agg.category_stats["implementation"]["achievement_rate"] == pytest.approx(0.5)
    assert agg.category_stats["implementation"]["avg_cost"] == pytest.approx(5.0)
    assert agg.category_stats["implementation"]["avg_duration"] == 30


def test_load_all_includes_effectiveness(tmp_claude_dir, sample_session_meta, sample_facet):
    """load_all() populates effectiveness data when facets exist."""
    # Write session-meta
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # Write facet
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "abc-123.json", "w") as f:
        json.dump(sample_facet, f)

    from claude_spend.data import load_all
    data = load_all(str(tmp_claude_dir))
    assert data.facets_loaded == 1
    assert len(data.effectiveness) == 1
    assert data.effectiveness[0].outcome == "fully_achieved"
    assert data.effectiveness[0].outcome_source == "facet"


def test_load_all_no_facets(tmp_claude_dir, sample_session_meta):
    """load_all() uses proxy when no facets exist."""
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    sample_session_meta.update({"git_commits": 3, "tool_errors": 0, "user_interruptions": 0})
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    from claude_spend.data import load_all
    data = load_all(str(tmp_claude_dir))
    assert data.facets_loaded == 0
    assert data.proxied_count == 1
    assert len(data.effectiveness) == 1
    assert data.effectiveness[0].outcome_source == "proxy"


def test_build_effectiveness_without_facet():
    from claude_spend.data import SessionMeta, SessionSummary
    from claude_spend.effectiveness import build_session_effectiveness

    session = SessionSummary(session_id="s2", estimated_cost=2.00)
    meta = SessionMeta(session_id="s2", git_commits=2, tool_errors=0, user_interruptions=0, duration_minutes=15)

    result = build_session_effectiveness(
        session=session, meta=meta, facet=None,
        category_avg_costs={}, median_duration=30,
    )
    assert result.outcome == "likely_achieved"
    assert result.outcome_source == "proxy"


def test_effectiveness_end_to_end(tmp_claude_dir, sample_session_meta, sample_facet, sample_jsonl_messages):
    """Full pipeline: meta + facet + JSONL -> effectiveness data on DashboardData."""
    # Write session-meta with extended fields
    sample_session_meta.update({
        "git_commits": 2, "tool_errors": 0, "user_interruptions": 0,
        "lines_added": 100, "files_modified": 3,
    })
    meta_dir = tmp_claude_dir / "usage-data" / "session-meta"
    with open(meta_dir / "abc-123.json", "w") as f:
        json.dump(sample_session_meta, f)

    # Write facet
    facets_dir = tmp_claude_dir / "usage-data" / "facets"
    facets_dir.mkdir(parents=True, exist_ok=True)
    with open(facets_dir / "abc-123.json", "w") as f:
        json.dump(sample_facet, f)

    # Write JSONL
    project_dir = tmp_claude_dir / "projects" / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)
    with open(project_dir / "abc-123.jsonl", "w") as f:
        for msg in sample_jsonl_messages:
            f.write(json.dumps(msg) + "\n")

    from claude_spend.data import load_all
    data = load_all(str(tmp_claude_dir))

    # Verify existing data still works
    assert len(data.sessions) == 1
    assert data.sessions[0].estimated_cost > 0

    # Verify effectiveness layer
    assert data.facets_loaded == 1
    assert len(data.effectiveness) == 1
    eff = data.effectiveness[0]
    assert eff.outcome == "fully_achieved"
    assert eff.outcome_source == "facet"
    assert eff.goal_categories == {"debugging_investigation": 1, "implementation": 1}

    # Verify aggregates
    assert data.effectiveness_agg is not None
    assert data.effectiveness_agg.achievement_rate == 1.0
