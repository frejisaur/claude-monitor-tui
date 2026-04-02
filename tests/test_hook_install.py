import json
import pytest
from claude_spend.hook_install import (
    HOOK_COMMAND,
    install_hook,
    uninstall_hook,
    is_hook_installed,
)


@pytest.fixture
def claude_dir(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    return d


@pytest.fixture
def settings_path(claude_dir):
    return claude_dir / "settings.json"


class TestInstallHook:
    def test_install_fresh_no_settings(self, claude_dir, settings_path):
        result = install_hook(claude_dir)
        assert result == "installed"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        stop_hooks = data["hooks"]["Stop"]
        commands = [h["command"] for h in stop_hooks]
        assert HOOK_COMMAND in commands

    def test_install_preserves_existing_hooks(self, claude_dir, settings_path):
        existing = {
            "model": "opus",
            "hooks": {
                "Stop": [{"command": "echo done"}]
            }
        }
        settings_path.write_text(json.dumps(existing))
        result = install_hook(claude_dir)
        assert result == "installed"
        data = json.loads(settings_path.read_text())
        assert data["model"] == "opus"
        commands = [h["command"] for h in data["hooks"]["Stop"]]
        assert "echo done" in commands
        assert HOOK_COMMAND in commands

    def test_install_preserves_existing_non_stop_hooks(self, claude_dir, settings_path):
        existing = {
            "hooks": {
                "PreToolUse": [{"command": "lint"}]
            }
        }
        settings_path.write_text(json.dumps(existing))
        install_hook(claude_dir)
        data = json.loads(settings_path.read_text())
        assert "PreToolUse" in data["hooks"]
        assert data["hooks"]["PreToolUse"] == [{"command": "lint"}]
        commands = [h["command"] for h in data["hooks"]["Stop"]]
        assert HOOK_COMMAND in commands

    def test_install_idempotent(self, claude_dir, settings_path):
        install_hook(claude_dir)
        result = install_hook(claude_dir)
        assert result == "already_installed"
        data = json.loads(settings_path.read_text())
        matching = [h for h in data["hooks"]["Stop"] if h["command"] == HOOK_COMMAND]
        assert len(matching) == 1


class TestUninstallHook:
    def test_uninstall_removes_hook(self, claude_dir):
        install_hook(claude_dir)
        assert is_hook_installed(claude_dir)
        result = uninstall_hook(claude_dir)
        assert result == "uninstalled"
        assert not is_hook_installed(claude_dir)

    def test_uninstall_preserves_other_hooks(self, claude_dir, settings_path):
        existing = {
            "hooks": {
                "Stop": [{"command": "echo done"}]
            }
        }
        settings_path.write_text(json.dumps(existing))
        install_hook(claude_dir)
        uninstall_hook(claude_dir)
        data = json.loads(settings_path.read_text())
        commands = [h["command"] for h in data["hooks"]["Stop"]]
        assert "echo done" in commands
        assert HOOK_COMMAND not in commands

    def test_uninstall_noop_when_not_installed(self, claude_dir):
        result = uninstall_hook(claude_dir)
        assert result == "not_installed"


class TestIsHookInstalled:
    def test_returns_false_no_settings(self, claude_dir):
        assert not is_hook_installed(claude_dir)

    def test_returns_true_after_install(self, claude_dir):
        install_hook(claude_dir)
        assert is_hook_installed(claude_dir)
