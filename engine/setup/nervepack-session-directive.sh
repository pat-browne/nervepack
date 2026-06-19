#!/usr/bin/env bash
# SessionStart hook: inject the "consult nervepack first" directive into every
# Claude Code session's context.
#
# Why this exists: nervepack skills are delivered as user skills, so their one-line
# descriptions load passively — but a passive list does not get used. Sessions
# defaulted to superpowers' process skills and ignored nervepack's domain knowledge.
# This hook gives nervepack the same forcing function superpowers has: it emits a
# forceful directive as SessionStart additionalContext so every session is told,
# up front, to consult nervepack's domain skills before working from first principles.
#
# Prints the directive (setup/nervepack-session-directive.md) jq-encoded into the
# SessionStart hook output schema. Runs SYNCHRONOUSLY (no `&`) — unlike
# 40-sync-nervepack.sh — because its stdout must reach the model as context.
#
# Registered by 51-install-nervepack-directive-hook.sh.
set -euo pipefail
# Inside a nervepack sub-agent (np-llm.sh sets NERVEPACK_AGENT=1)? bail — the
# directive must not recurse into agent contexts. Mirrors episodic-capture /
# np-session-flush / np-backcapture-sweep.
[[ -n "${NERVEPACK_AGENT:-}" ]] && exit 0
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled directive || exit 0; }

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIRECTIVE="$DIR/nervepack-session-directive.md"

# Fail open: if anything is missing, stay silent rather than break session start.
command -v jq >/dev/null || exit 0
[[ -f "$DIRECTIVE" ]] || exit 0

jq -Rs '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: .
  }
}' "$DIRECTIVE"
