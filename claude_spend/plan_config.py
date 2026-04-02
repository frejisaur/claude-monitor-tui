"""Plan budget constants and ~/.claude-spend/config.json management."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanBudget:
    """Budget limits for a Claude subscription plan."""
    name: str
    five_hour_budget: float   # estimated $ per 5h window
    weekly_budget: float      # estimated $ per 7d window
    monthly_price: int        # subscription price in $/mo


# Budget estimates derived from community research (not officially published by Anthropic).
# Sources:
#   - Faros.ai token limit guide: ~44k/88k/220k output tokens per 5h window
#   - claude-meter proxy intercepts: price-weighted usage correlates with 5h meter
#   - SSD Nodes pricing breakdown: $20/$100/$200 monthly tiers
# Confidence: MEDIUM for 5h (community consensus), LOW for weekly (less data).
# Users should override with custom_budgets if their observed limits differ.
PLAN_BUDGETS: dict[str, PlanBudget] = {
    "pro": PlanBudget(name="Pro", five_hour_budget=4.40, weekly_budget=20.0, monthly_price=20),
    "max5": PlanBudget(name="Max 5x", five_hour_budget=8.80, weekly_budget=100.0, monthly_price=100),
    "max20": PlanBudget(name="Max 20x", five_hour_budget=22.0, weekly_budget=200.0, monthly_price=200),
}

DEFAULT_PLAN = "max5"

_DEFAULT_CONFIG = {"plan": DEFAULT_PLAN, "custom_budgets": None}


def _config_path(config_dir: str) -> str:
    return os.path.join(config_dir, "config.json")


def load_plan_config(config_dir: str) -> dict:
    """Load config from config_dir/config.json. Returns defaults if missing."""
    path = _config_path(config_dir)
    if not os.path.isfile(path):
        return dict(_DEFAULT_CONFIG)
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "plan": data.get("plan", DEFAULT_PLAN),
            "custom_budgets": data.get("custom_budgets"),
        }
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_CONFIG)


def _ensure_secure_dir(config_dir: str) -> None:
    """Create directory with 0700 permissions (owner-only access)."""
    os.makedirs(config_dir, exist_ok=True)
    os.chmod(config_dir, 0o700)


def _write_secure_file(path: str, content: str) -> None:
    """Write file with 0600 permissions (owner read/write only)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)


def save_plan_config(
    config_dir: str,
    plan: str = DEFAULT_PLAN,
    custom_budgets: dict | None = None,
) -> None:
    """Write config to config_dir/config.json, creating directory if needed."""
    _ensure_secure_dir(config_dir)
    _write_secure_file(
        _config_path(config_dir),
        json.dumps({"plan": plan, "custom_budgets": custom_budgets}, indent=2),
    )


def get_active_budget(config_dir: str) -> PlanBudget:
    """Return the active PlanBudget based on config. Falls back to DEFAULT_PLAN."""
    config = load_plan_config(config_dir)
    plan = config["plan"]

    if plan == "custom" and config["custom_budgets"]:
        cb = config["custom_budgets"]
        return PlanBudget(
            name="Custom",
            five_hour_budget=cb.get("5h_budget", PLAN_BUDGETS[DEFAULT_PLAN].five_hour_budget),
            weekly_budget=cb.get("weekly_budget", PLAN_BUDGETS[DEFAULT_PLAN].weekly_budget),
            monthly_price=0,
        )

    return PLAN_BUDGETS.get(plan, PLAN_BUDGETS[DEFAULT_PLAN])
