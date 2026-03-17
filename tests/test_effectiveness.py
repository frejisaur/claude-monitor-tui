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
