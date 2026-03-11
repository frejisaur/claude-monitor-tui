"""Data loading, parsing, aggregation, and cost calculation for claude-spend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Pricing in $/MTok
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
}

FALLBACK_MODEL = "claude-sonnet-4-6"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_write_tokens + self.cache_read_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )


def calculate_cost(usage: TokenUsage, model: str) -> float:
    """Calculate estimated API cost for a token usage at given model's pricing."""
    prices = PRICING.get(model, PRICING[FALLBACK_MODEL])
    return (
        (usage.input_tokens / 1_000_000) * prices["input"]
        + (usage.output_tokens / 1_000_000) * prices["output"]
        + (usage.cache_write_tokens / 1_000_000) * prices["cache_write"]
        + (usage.cache_read_tokens / 1_000_000) * prices["cache_read"]
    )
