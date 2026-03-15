# PyPI Distribution Design for claude-monitor-tui

**Date:** 2026-03-15
**Status:** Draft

## Problem

claude-spend-tui (to be renamed claude-monitor-tui) is a Textual-based terminal dashboard for monitoring Claude Code usage. It currently has no distribution mechanism — install requires cloning the repo and running `pip install -e .`. We need a low-friction, security-forward way for any developer on macOS or Linux to install and run it.

## Decision

Publish to PyPI using GitHub Actions with Trusted Publishers (OIDC). Users install via `pipx install claude-monitor-tui` and run `claude-monitor`.

## Design

### 1. Package Identity

| Field | Value |
|-|-|
| PyPI package name | `claude-monitor-tui` |
| CLI entry point | `claude-monitor` |
| Python module | `claude_spend` (unchanged internally) |
| Python requirement | >=3.10 |
| Platforms | macOS, Linux |

The internal module name (`claude_spend`) stays unchanged to avoid a disruptive rename of the entire codebase. Only the user-facing names change.

### 2. pyproject.toml Updates

Add/update the following fields:

- `name` = `"claude-monitor-tui"`
- `description` — one-line summary of the tool
- `license` — choose and declare (e.g., MIT)
- `authors` — name and email
- `readme` = `"README.md"`
- `urls` — `Homepage`, `Repository`, `Issues` pointing to the GitHub repo
- `classifiers` — Python version, OS, framework classifiers
- `scripts` — rename entry point from `claude-spend` to `claude-monitor` (pointing to same `claude_spend.dashboard:main`)
- **Versioning** — keep static `version` in `pyproject.toml`. The publish workflow will validate that the git tag matches the declared version before publishing.
- **Build targets** — add `[tool.hatch.build.targets.wheel] packages = ["claude_spend"]` so hatchling finds the source directory despite the package name divergence
- **Test dependencies** — declare `[project.optional-dependencies] dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0"]` for CI usage

### 3. GitHub Actions Workflows

Two workflows:

**CI (`.github/workflows/ci.yml`)** — runs on every push to `main` and every PR:
- Checkout code
- Set up Python 3.10, 3.11, 3.12
- Install dependencies
- Run `pytest`

**Publish (`.github/workflows/publish.yml`)** — runs on tag push matching `v*`:
1. **Validate version** — check that the git tag (e.g., `v1.2.0`) matches the version in `pyproject.toml` (`1.2.0`). Fail fast on mismatch.
2. Run the full test suite (same as CI)
3. Build the package (`python -m build` — produces sdist + wheel)
4. Publish to PyPI using Trusted Publishers (OIDC, no API tokens)
4. Create a GitHub Release with auto-generated release notes and attach build artifacts

The publish workflow uses a dedicated `release` environment in GitHub to scope the OIDC trust.

### 4. PyPI Trusted Publishers (Security Model)

Trusted Publishers use OpenID Connect to establish trust between GitHub Actions and PyPI:

- **No API tokens** are stored in GitHub Secrets — eliminates token theft risk
- **Cryptographic provenance** — PyPI verifies the build originated from a specific GitHub repository, workflow file, and environment
- **Verifiable by users** — anyone can check that a published package was built by CI, not uploaded manually
- **One-time setup** — configure in PyPI's web UI by registering the GitHub repo, workflow filename, and environment name

### 5. Release Process

Developer workflow:

1. Update version in `pyproject.toml`
2. Commit and push to `main`
3. Create and push a git tag: `git tag v1.0.0 && git push --tags`
4. GitHub Actions runs tests, builds, and publishes automatically
5. GitHub Release is created with auto-generated notes

### 6. User Install Experience

README documents three install methods:

```bash
# Recommended (isolated install, no venv needed)
pipx install claude-monitor-tui

# Alternative with uv
uv tool install claude-monitor-tui

# With pip
pip install claude-monitor-tui
```

Then run: `claude-monitor`

**Prerequisite:** Python 3.10+ (noted in README with install guidance).

### 7. README

Create a `README.md` covering:

- What the tool does (one paragraph + screenshot)
- Install instructions (the three methods above)
- Usage basics
- Requirements (Python 3.10+)
- Contributing / development setup
- License

### 8. GitHub Repository Setup

The project already has a local git repo with commit history but no remote.

- Create a GitHub repo (e.g., `username/claude-monitor-tui`)
- Add remote and push existing history
- Register as Trusted Publisher on PyPI
- Optionally: branch protection on `main` requiring CI to pass

## Out of Scope

- Homebrew tap (can layer on later if demand warrants)
- Standalone binaries (PyInstaller/Nuitka)
- Windows support
- Docker images
- Auto-update mechanism

## Components Changed

| File | Change |
|-|-|
| `pyproject.toml` | Rename package, add metadata, update entry point, build config |
| `README.md` | Create with install/usage docs |
| `LICENSE` | Create license file (MIT or chosen license) |
| `.github/workflows/ci.yml` | Create CI workflow |
| `.github/workflows/publish.yml` | Create publish workflow |
