#!/usr/bin/env bash
# Merge Pat's global dev-command allowlist into ~/.claude/settings.json so the
# same commands are pre-approved across ALL Claude Code sessions and machines —
# instead of re-approving them per project (the "always allow" button only ever
# writes to a project's .claude/settings.local.json).
#
# Idempotent: re-running only appends rules that aren't already present, and
# never touches the rest of settings.json (hooks, plugins, theme, the read-only
# baseline allowlist, etc.).
#
# SECURITY NOTE: this list is intentionally broad for convenience and includes
# arbitrary-code / destructive patterns (git *, node *, npx *, python3 *). It is
# Pat's deliberate trade-off for a single-user dev machine. Trim ALLOW below if
# a machine needs a tighter posture.
set -euo pipefail

command -v jq >/dev/null 2>&1 || { echo "90-install-claude-permissions: jq not found (see np-env-ubuntu-claude-dev-setup)"; exit 1; }

SETTINGS="${CLAUDE_SETTINGS:-${HOME}/.claude/settings.json}"
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

# Pre-approved dev commands — canonical list in allowlist-entries.txt (single
# source of truth shared with 91-remove-claude-permissions.sh / the toggle).
ENTRIES="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/allowlist-entries.txt"
ALLOW="$(jq -R -s 'split("\n") | map(select(length>0))' "$ENTRIES")"

before="$(jq '(.permissions.allow // []) | length' "$SETTINGS")"
tmp="$(mktemp)"
jq --argjson add "$ALLOW" '
  .permissions = (.permissions // {})
  | .permissions.allow = ((.permissions.allow // []) + ($add - (.permissions.allow // [])))
' "$SETTINGS" > "$tmp"
jq -e . "$tmp" >/dev/null   # fail loudly rather than write malformed settings
mv "$tmp" "$SETTINGS"
after="$(jq '(.permissions.allow // []) | length' "$SETTINGS")"

echo "claude permissions: dev allowlist merged into ${SETTINGS} (allow ${before} -> ${after})"
