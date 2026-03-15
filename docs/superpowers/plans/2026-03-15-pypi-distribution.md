# PyPI Distribution Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package claude-spend-tui as `claude-monitor-tui` on PyPI with automated CI/CD via GitHub Actions Trusted Publishers.

**Architecture:** Update pyproject.toml with new package name/metadata/build config, create LICENSE and README, add two GitHub Actions workflows (CI on PR/push, publish on tag). Manual one-time setup for GitHub repo creation and PyPI Trusted Publisher registration.

**Tech Stack:** hatchling (build), GitHub Actions (CI/CD), PyPI Trusted Publishers (OIDC), pytest (testing)

**Spec:** `docs/superpowers/specs/2026-03-15-pypi-distribution-design.md`

---

## Chunk 1: Package Configuration

### Task 1: Update pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml with new name, metadata, and build config**

Replace the entire contents of `pyproject.toml` with:

```toml
[project]
name = "claude-monitor-tui"
version = "1.0.0"
description = "Terminal dashboard for monitoring Claude Code API usage and costs"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [
    { name = "Abiz" },
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Utilities",
]
dependencies = [
    "textual>=0.47.0",
    "textual-plotext>=0.2.0",
    "plotext>=5.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[project.scripts]
claude-monitor = "claude_spend.dashboard:main"

[project.urls]
Homepage = "https://github.com/abizjak/claude-monitor-tui"
Repository = "https://github.com/abizjak/claude-monitor-tui"
Issues = "https://github.com/abizjak/claude-monitor-tui/issues"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["claude_spend"]
```

**Important:** Before committing, ask the user for their GitHub username and replace all occurrences of placeholder usernames in `pyproject.toml` URLs and `README.md` clone URL.

- [ ] **Step 2: Verify the package builds correctly**

Run:
```bash
pip install build && python -m build
```

Expected: Successful build producing `dist/claude_monitor_tui-1.0.0.tar.gz` and `dist/claude_monitor_tui-1.0.0-py3-none-any.whl`

- [ ] **Step 3: Verify the entry point works from a clean install**

Run:
```bash
pip install dist/claude_monitor_tui-1.0.0-py3-none-any.whl && which claude-monitor
```

Expected: `claude-monitor` binary is on PATH

- [ ] **Step 4: Run existing tests to confirm nothing broke**

Run:
```bash
pytest tests/ -v
```

Expected: All existing tests pass.

- [ ] **Step 5: Clean up build artifacts and commit**

Run:
```bash
rm -rf dist/ *.egg-info
git add pyproject.toml
git commit -m "chore: rename package to claude-monitor-tui and add PyPI metadata"
```

---

### Task 2: Create LICENSE file

**Files:**
- Create: `LICENSE`

- [ ] **Step 1: Create MIT LICENSE file**

Create `LICENSE` with the following content:

```
MIT License

Copyright (c) 2026 Abiz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "chore: add MIT license"
```

---

### Task 3: Create README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create README.md**

```markdown
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
git clone https://github.com/USERNAME/claude-monitor-tui.git
cd claude-monitor-tui
pip install -e ".[dev]"
pytest
```

## License

MIT
```

**Important:** Replace `USERNAME` with the actual GitHub username (same one used in Task 1).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with install and usage instructions"
```

---

## Chunk 2: CI/CD Workflows

### Task 4: Create CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/` directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Create CI workflow file**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run tests
        run: pytest tests/ -v
```

- [ ] **Step 3: Validate workflow syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('Valid YAML')"
```

Expected: `Valid YAML` (no syntax errors)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add test workflow for PRs and main branch"
```

---

### Task 5: Create publish workflow

**Files:**
- Create: `.github/workflows/publish.yml`

- [ ] **Step 1: Create publish workflow file**

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  push:
    tags: ["v*"]

jobs:
  validate-version:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Validate tag matches pyproject.toml version
        run: |
          TAG_VERSION="${GITHUB_REF_NAME#v}"
          PKG_VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
          if [ "$TAG_VERSION" != "$PKG_VERSION" ]; then
            echo "ERROR: Tag version ($TAG_VERSION) does not match pyproject.toml version ($PKG_VERSION)"
            exit 1
          fi
          echo "Version match: $TAG_VERSION"

  test:
    needs: validate-version
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run tests
        run: pytest tests/ -v

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install build
        run: pip install build

      - name: Build package
        run: python -m build

      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: release
    permissions:
      id-token: write
    steps:
      - name: Download build artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  github-release:
    needs: publish
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Download build artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
          files: dist/*
```

- [ ] **Step 2: Validate workflow syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml')); print('Valid YAML')"
```

Expected: `Valid YAML`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci: add PyPI publish workflow with Trusted Publishers"
```

---

### Task 6: Update .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add build artifact patterns to .gitignore**

Append to `.gitignore`:

```
dist/
build/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add build artifacts to gitignore"
```

---

## Chunk 3: Manual Setup Steps (Reference)

### Task 7: GitHub repo and PyPI setup (manual — not automated)

These are manual steps the developer performs once. They are documented here for reference, not executed by the agent.

- [ ] **Step 1: Create GitHub repository**

Go to GitHub and create a new repo named `claude-monitor-tui`. Do not initialize with README (we already have one).

- [ ] **Step 2: Add remote and push**

```bash
git remote add origin git@github.com:USERNAME/claude-monitor-tui.git
git branch -M main
git push -u origin main
```

- [ ] **Step 3: Create `release` environment on GitHub**

Go to repo Settings → Environments → New environment → Name it `release`.

- [ ] **Step 4: Register Trusted Publisher on PyPI**

1. Go to https://pypi.org/manage/account/publishing/
2. Add a new pending publisher:
   - PyPI project name: `claude-monitor-tui`
   - Owner: your GitHub username
   - Repository: `claude-monitor-tui`
   - Workflow name: `publish.yml`
   - Environment name: `release`

- [ ] **Step 5: Tag and publish first release**

```bash
git tag v1.0.0
git push --tags
```

This triggers the publish workflow. Verify on PyPI that the package appears.

- [ ] **Step 6: Verify install works**

```bash
pipx install claude-monitor-tui
claude-monitor
```
