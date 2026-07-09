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

# Content-fed routing fragment (personal/domain trigger->skill rows, spec §3): folded
# into the SAME additionalContext string as the engine directive — NOT printed as raw
# text after the JSON blob. Claude Code requires SessionStart hook stdout to be a
# single valid JSON document; trailing non-JSON text after it fails parsing and drops
# the additionalContext entirely (defeating fail-open for the common case where a
# fragment IS present). jq's `-Rs` (raw + slurp) over multiple file args concatenates
# their raw bytes into one string — the engine `.md` always ends with a trailing
# newline, so appending the fragment file reproduces "newline then fragment" without
# extra command substitution. Fail-open: absent content dir/fragment -> engine
# directive only, no error (this hook runs on every SessionStart). No
# timestamps/volatile fields in the fragment, so the composed output stays
# byte-stable (invariant 11).
_inputs=("$DIRECTIVE")
# Feed a directive-routing.md fragment from EVERY merge root (team[0..n] > personal),
# highest-precedence first, so a team overlay's domain-skill routing reaches sessions
# — not personal-only. np_merge_roots (np-layer-lib.sh) honors the `team` toggle and
# `team.merge` mode; with no team configured it yields just the personal root, so this
# stays byte-identical to the personal-only behavior. Fail-open: a missing lib or an
# empty merge set appends nothing and the engine directive stands alone.
_npll="$DIR/np-layer-lib.sh"
if [[ -r "$_npll" ]]; then
  # shellcheck source=/dev/null
  source "$_npll"
  while IFS= read -r _root; do
    [[ -n "$_root" ]] || continue
    _frag="$_root/directive-routing.md"
    [[ -f "$_frag" ]] && _inputs+=("$_frag")
  done < <(np_merge_roots 2>/dev/null)
fi

jq -Rs '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: .
  }
}' "${_inputs[@]}"
