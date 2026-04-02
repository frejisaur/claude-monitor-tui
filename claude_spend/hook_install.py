import json
from pathlib import Path

HOOK_COMMAND = "python3 -m claude_spend.hook"


def _settings_path(claude_dir: Path) -> Path:
    return claude_dir / "settings.json"


def _load_settings(claude_dir: Path) -> dict:
    path = _settings_path(claude_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(claude_dir: Path, data: dict) -> None:
    path = _settings_path(claude_dir)
    path.write_text(json.dumps(data, indent=2) + "\n")


def is_hook_installed(claude_dir: Path) -> bool:
    settings = _load_settings(claude_dir)
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    return any(h.get("command") == HOOK_COMMAND for h in stop_hooks)


def install_hook(claude_dir: Path) -> str:
    if is_hook_installed(claude_dir):
        return "already_installed"
    settings = _load_settings(claude_dir)
    settings.setdefault("hooks", {}).setdefault("Stop", []).append(
        {"command": HOOK_COMMAND}
    )
    _save_settings(claude_dir, settings)
    return "installed"


def uninstall_hook(claude_dir: Path) -> str:
    if not is_hook_installed(claude_dir):
        return "not_installed"
    settings = _load_settings(claude_dir)
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    settings["hooks"]["Stop"] = [
        h for h in stop_hooks if h.get("command") != HOOK_COMMAND
    ]
    _save_settings(claude_dir, settings)
    return "uninstalled"


def main_install() -> None:
    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(exist_ok=True)
    result = install_hook(claude_dir)
    if result == "installed":
        print("claude-spend hook installed successfully.")
    else:
        print("claude-spend hook is already installed.")


def main_uninstall() -> None:
    claude_dir = Path.home() / ".claude"
    result = uninstall_hook(claude_dir)
    if result == "uninstalled":
        print("claude-spend hook uninstalled successfully.")
    else:
        print("claude-spend hook was not installed.")
