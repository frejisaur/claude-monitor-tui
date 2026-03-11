---
description: "Launch token usage analytics dashboard"
---

Launch the claude-spend TUI dashboard in a new terminal window. Execute this command:

```bash
DAYS="${ARGUMENTS:-30}" && TERM_APP="${TERM_PROGRAM:-Terminal.app}" && TERM_NAME="${TERM_APP%.app}" && osascript -e "tell application \"$TERM_NAME\" to activate" -e "tell application \"$TERM_NAME\" to do script \"uvx --from '$HOME/code/claude-spend-tui' claude-spend --days $DAYS\""
```

If $ARGUMENTS is empty, the default is 30 days.
Pass the user's argument as the --days value. Examples: `/spend 7` → `--days 7`, `/spend all` → `--days all`, `/spend` → `--days 30`.

Tell the user the dashboard has been launched in a new terminal window.
