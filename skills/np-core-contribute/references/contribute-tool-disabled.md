# When the contribute tool says disabled

Two separate params gate writes. `evaluator.implement_mode=direct` lives in `~/.config/nervepack/toggles.local`. The `nervepack_contribute` MCP tool uses `mcp.contribute`, set in `engine/setup/toggles.conf` (`mcp|...|writes=on,contribute=off`). The toggle `list` view shows neither. Grep both files for `contribute` before asking the user to flip it again. Fallback: a hand-written commit in a worktree off `origin/main`.
