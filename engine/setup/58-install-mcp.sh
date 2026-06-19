#!/usr/bin/env bash
# Register the nervepack MCP server with Claude Code (user scope), idempotently.
# Toggle-gated on `mcp`. Remove with: setup/58-install-mcp.sh remove
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
source "$HERE/np-toggle-lib.sh" 2>/dev/null || true
command -v claude >/dev/null || { echo "58-install-mcp: claude CLI not found; skipping" >&2; exit 0; }

if [[ "${1:-}" == "remove" ]]; then
  claude mcp remove nervepack -s user >/dev/null 2>&1 || true
  echo "58-install-mcp: removed nervepack MCP server"
  exit 0
fi

np_enabled mcp || { echo "58-install-mcp: mcp toggle off; skipping" >&2; exit 0; }

# Idempotent: remove any stale entry, then add the current path.
claude mcp remove nervepack -s user >/dev/null 2>&1 || true
claude mcp add nervepack -s user -- "$NP/engine/bin/nervepack-mcp" \
  && echo "58-install-mcp: registered nervepack MCP server (user scope)"
exit 0
