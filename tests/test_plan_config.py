"""Tests for plan budget constants and config file management."""

import json
import os
import pytest

from claude_spend.plan_config import (
    PLAN_BUDGETS, PlanBudget, load_plan_config, save_plan_config, get_active_budget,
)


class TestPlanBudgets:
    def test_pro_budget_has_required_fields(self):
        b = PLAN_BUDGETS["pro"]
        assert isinstance(b, PlanBudget)
        assert b.five_hour_budget > 0
        assert b.weekly_budget > 0
        assert b.monthly_price == 20

    def test_max5_budget_is_proportional_to_pro(self):
        pro = PLAN_BUDGETS["pro"]
        max5 = PLAN_BUDGETS["max5"]
        assert max5.five_hour_budget == pytest.approx(pro.five_hour_budget * 2, rel=0.1)
        assert max5.weekly_budget == pytest.approx(pro.weekly_budget * 5, rel=0.05)
        assert max5.monthly_price == 100
        assert max5.five_hour_budget < max5.weekly_budget

    def test_max20_budget_is_proportional_to_pro(self):
        pro = PLAN_BUDGETS["pro"]
        max20 = PLAN_BUDGETS["max20"]
        assert max20.five_hour_budget == pytest.approx(pro.five_hour_budget * 5, rel=0.1)
        assert max20.weekly_budget == pytest.approx(pro.weekly_budget * 10, rel=0.05)
        assert max20.monthly_price == 200
        assert max20.five_hour_budget < max20.weekly_budget

    def test_all_plans_present(self):
        assert set(PLAN_BUDGETS.keys()) == {"pro", "max5", "max20"}


class TestConfigFile:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        config = load_plan_config(str(tmp_path / "nonexistent"))
        assert config["plan"] == "max5"
        assert config["custom_budgets"] is None

    def test_save_and_load_roundtrip(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="pro")
        loaded = load_plan_config(config_dir)
        assert loaded["plan"] == "pro"
        assert loaded["custom_budgets"] is None

    def test_save_with_custom_budgets(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="custom", custom_budgets={"5h_budget": 10.0, "weekly_budget": 150.0})
        loaded = load_plan_config(config_dir)
        assert loaded["plan"] == "custom"
        assert loaded["custom_budgets"]["5h_budget"] == 10.0

    def test_get_active_budget_named_plan(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="pro")
        budget = get_active_budget(config_dir)
        assert budget == PLAN_BUDGETS["pro"]

    def test_get_active_budget_custom(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="custom", custom_budgets={"5h_budget": 10.0, "weekly_budget": 150.0})
        budget = get_active_budget(config_dir)
        assert budget.five_hour_budget == 10.0
        assert budget.weekly_budget == 150.0

    def test_save_creates_secure_directory(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        save_plan_config(config_dir, plan="pro")
        dir_stat = os.stat(config_dir)
        assert oct(dir_stat.st_mode)[-3:] == "700"
        file_stat = os.stat(os.path.join(config_dir, "config.json"))
        assert oct(file_stat.st_mode)[-3:] == "600"

    def test_get_active_budget_unknown_plan_falls_back(self, tmp_path):
        config_dir = str(tmp_path / "claude-spend")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "config.json"), "w") as f:
            json.dump({"plan": "nonexistent", "custom_budgets": None}, f)
        budget = get_active_budget(config_dir)
        assert budget == PLAN_BUDGETS["max5"]
