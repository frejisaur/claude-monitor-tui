from claude_spend.data import TokenUsage, PRICING, calculate_cost, resolve_model_id


def test_token_usage_total():
    usage = TokenUsage(input_tokens=1000, output_tokens=500, cache_write_tokens=200, cache_read_tokens=300)
    assert usage.total == 2000


def test_token_usage_zero():
    usage = TokenUsage()
    assert usage.total == 0


def test_token_usage_add():
    a = TokenUsage(input_tokens=100, output_tokens=50, cache_write_tokens=20, cache_read_tokens=30)
    b = TokenUsage(input_tokens=200, output_tokens=100, cache_write_tokens=40, cache_read_tokens=60)
    c = a + b
    assert c.input_tokens == 300
    assert c.output_tokens == 150
    assert c.cache_write_tokens == 60
    assert c.cache_read_tokens == 90


def test_calculate_cost_opus():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    cost = calculate_cost(usage, "claude-opus-4-6")
    # $15 input + $75 output + $18.75 cache_write + $1.50 cache_read = $110.25
    assert abs(cost - 110.25) < 0.01


def test_calculate_cost_sonnet():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    cost = calculate_cost(usage, "claude-sonnet-4-6")
    # $3 + $15 + $3.75 + $0.30 = $22.05
    assert abs(cost - 22.05) < 0.01


def test_calculate_cost_haiku():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    cost = calculate_cost(usage, "claude-haiku-4-5-20251001")
    # $0.80 + $4.00 + $1.00 + $0.08 = $5.88
    assert abs(cost - 5.88) < 0.01


def test_calculate_cost_unknown_model_falls_back_to_sonnet():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0, cache_write_tokens=0, cache_read_tokens=0)
    cost = calculate_cost(usage, "claude-unknown-model")
    # Falls back to sonnet: $3/MTok
    assert abs(cost - 3.0) < 0.01


def test_resolve_model_id_short_names():
    """Short names fuzzy-match against PRICING keys, version-agnostic."""
    assert resolve_model_id("haiku") == "claude-haiku-4-5-20251001"
    assert resolve_model_id("sonnet") == "claude-sonnet-4-6"
    assert resolve_model_id("opus") == "claude-opus-4-6"


def test_resolve_model_id_full_names_pass_through():
    assert resolve_model_id("claude-opus-4-6") == "claude-opus-4-6"
    assert resolve_model_id("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_resolve_model_id_unknown_passes_through():
    assert resolve_model_id("unknown") == "unknown"
    assert resolve_model_id("some-future-model") == "some-future-model"


def test_session_summary_default_start_time_is_aware():
    """SessionSummary default start_time must be timezone-aware to avoid TypeError on sort."""
    from claude_spend.data import SessionSummary
    s = SessionSummary()
    assert s.start_time.tzinfo is not None


def test_session_summary_sortable_with_session_meta():
    """SessionSummary and SessionMeta defaults must be comparable (both aware)."""
    from claude_spend.data import SessionSummary, SessionMeta
    ss = SessionSummary()
    sm = SessionMeta()
    assert ss.start_time <= sm.start_time or ss.start_time >= sm.start_time


def test_session_summary_cache_hit_ratio():
    from claude_spend.data import SessionSummary, TokenUsage
    s = SessionSummary(
        usage_by_model={"claude-opus-4-6": TokenUsage(
            input_tokens=1000, output_tokens=500,
            cache_write_tokens=200, cache_read_tokens=800,
        )},
    )
    # cache_hit_ratio = cache_read / (cache_read + cache_write + input) = 800 / 2000 = 0.4
    assert abs(s.cache_hit_ratio - 0.4) < 0.01


def test_session_summary_cache_rw_ratio():
    from claude_spend.data import SessionSummary, TokenUsage
    s = SessionSummary(
        usage_by_model={"claude-opus-4-6": TokenUsage(
            input_tokens=1000, output_tokens=500,
            cache_write_tokens=200, cache_read_tokens=800,
        )},
    )
    # cache_rw_ratio = cache_read / max(1, cache_write) = 800 / 200 = 4.0
    assert abs(s.cache_rw_ratio - 4.0) < 0.01


def test_session_summary_cache_ratios_zero_tokens():
    from claude_spend.data import SessionSummary, TokenUsage
    s = SessionSummary(
        usage_by_model={"claude-opus-4-6": TokenUsage()},
    )
    assert s.cache_hit_ratio == 0.0
    assert s.cache_rw_ratio == 0.0


def test_aggregate_by_skill_basic():
    from claude_spend.data import SessionSummary, TokenUsage, aggregate_by_skill
    sessions = [
        SessionSummary(
            session_id="s1",
            skill_invocations=["brainstorming", "execute-plan"],
            estimated_cost=60.0,
            usage_by_model={"claude-opus-4-6": TokenUsage(
                input_tokens=1000, output_tokens=500,
                cache_write_tokens=200, cache_read_tokens=800,
            )},
            duration_minutes=120,
            turn_count=30,
        ),
        SessionSummary(
            session_id="s2",
            skill_invocations=["brainstorming"],
            estimated_cost=40.0,
            usage_by_model={"claude-opus-4-6": TokenUsage(
                input_tokens=1000, output_tokens=500,
                cache_write_tokens=100, cache_read_tokens=900,
            )},
            duration_minutes=60,
            turn_count=15,
        ),
        SessionSummary(
            session_id="s3",
            skill_invocations=[],
            estimated_cost=25.0,
            usage_by_model={"claude-opus-4-6": TokenUsage(
                input_tokens=500, output_tokens=250,
                cache_write_tokens=50, cache_read_tokens=400,
            )},
            duration_minutes=30,
            turn_count=8,
        ),
    ]
    baseline = 25.0  # only s3 has no skills
    aggs = aggregate_by_skill(sessions, baseline)

    # brainstorming appears in s1 and s2
    brain = next(a for a in aggs if a.skill_name == "brainstorming")
    assert brain.invocation_count == 2
    assert abs(brain.avg_session_cost - 50.0) < 0.01  # (60+40)/2
    assert abs(brain.cost_delta - 25.0) < 0.01  # 50 - 25

    # execute-plan appears in s1 only
    ep = next(a for a in aggs if a.skill_name == "execute-plan")
    assert ep.invocation_count == 1
    assert abs(ep.avg_session_cost - 60.0) < 0.01

    # sorted by cost_delta descending
    assert aggs[0].cost_delta >= aggs[-1].cost_delta


def test_aggregate_by_skill_empty():
    from claude_spend.data import aggregate_by_skill
    aggs = aggregate_by_skill([], 0.0)
    assert aggs == []


def test_aggregate_by_skill_whitespace_name(tmp_path):
    """Whitespace skill names in JSONL are normalized to '(unnamed)' by parse_conversation_jsonl."""
    import json
    from claude_spend.data import parse_conversation_jsonl

    jsonl_path = tmp_path / "session.jsonl"
    msg = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-6",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_ws1",
                    "name": "Skill",
                    "input": {"skill": "   "},
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
        "timestamp": "2026-03-05T10:01:00.000Z",
    }
    with open(jsonl_path, "w") as f:
        f.write(json.dumps(msg) + "\n")

    data = parse_conversation_jsonl(str(jsonl_path))
    assert "(unnamed)" in data.skill_invocations
