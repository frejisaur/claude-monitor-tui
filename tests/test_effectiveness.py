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
