---
description: "Launch token usage analytics dashboard"
---

Run the claude-spend TUI dashboard. Execute this command:

```bash
cd "$HOME/code/claude-spend-tui" && pip install -q -r requirements.txt 2>/dev/null && python3 scripts/dashboard.py --days $ARGUMENTS
```

If $ARGUMENTS is empty, use `--days 30` as default.
Pass the user's argument as the --days value. Examples: `/spend 7` → `--days 7`, `/spend all` → `--days all`, `/spend` → `--days 30`.
