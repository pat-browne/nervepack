#!/usr/bin/env bash
# Pre-warm the Serena MCP server so its first connection doesn't time out.
#
# The `serena` plugin's .mcp.json launches the server with
#   uvx --from git+https://github.com/oraios/serena serena start-mcp-server
# On a fresh machine the FIRST such run clones + builds the package (a minute
# or more). If Claude Code starts before that's warm, the MCP handshake times
# out and the serena__* tools silently don't load for the session.
#
# This script does that one-time clone/build ahead of time by invoking the
# same git source with a cheap subcommand, populating the uv cache. Run it
# after 20-claude-plugins.sh, then restart Claude Code so it connects.
# Idempotent: a second run is a fast cache hit.
set -euo pipefail

# Must match the source string in serena's .mcp.json exactly — otherwise the
# cache we populate here won't be the one the MCP handshake resolves.
SERENA_SRC="git+https://github.com/oraios/serena"

if ! command -v uvx >/dev/null; then
  echo "uvx not found on PATH. Serena launches via uv, not pipx." >&2
  echo "Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "(see np-env-ubuntu-claude-dev-setup), then re-run this script." >&2
  exit 1
fi

echo "==> Pre-warming Serena ($SERENA_SRC) — first run clones + builds, please wait..."
uvx --from "$SERENA_SRC" serena --help >/dev/null

echo
echo "Serena pre-warmed. Restart Claude Code so it connects and the serena__* tools appear."
