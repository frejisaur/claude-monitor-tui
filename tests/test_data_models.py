from claude_spend.data import TokenUsage, PRICING, calculate_cost


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
