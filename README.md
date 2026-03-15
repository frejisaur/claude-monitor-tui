# claude-monitor-tui

Terminal dashboard for monitoring your Claude Code API usage and costs.

Built with [Textual](https://github.com/Textualize/textual) for a rich terminal UI experience.

<!-- TODO: Add screenshot here once published -->

## Install

Requires Python 3.10+.

```bash
# Recommended (isolated install)
pipx install claude-monitor-tui

# Alternative with uv
uv tool install claude-monitor-tui

# With pip
pip install claude-monitor-tui
```

## Usage

```bash
claude-monitor
```

## Development

```bash
git clone https://github.com/frejisaur/claude-monitor-tui.git
cd claude-monitor-tui
pip install -e ".[dev]"
pytest
```

## License

MIT
