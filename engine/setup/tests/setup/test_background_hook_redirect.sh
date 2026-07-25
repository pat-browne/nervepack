#!/usr/bin/env bash
# np-test: background-hook-redirect | happy
# Regression: the long-running backgrounded (`&`) lifecycle hooks MUST redirect
# stdout+stderr (`>/dev/null 2>&1 &`).
#
# Why this matters: a `&` child inherits the hook command's stdout pipe and holds it
# open for its whole run. Claude Code reads a hook's stdout to EOF (that's how the
# SessionStart directive gets injected), so a backgrounded LONG-running hook WITHOUT a
# redirect blocks session start until the child exits — the `&` does not detach it.
# The np-backcapture-sweep can run for minutes, so a missing redirect turned into
# multi-minute session starts (#101). See np-kb-claude-headless-scripting.
#
# Phase 13: the source of truth is now engine/setup/hooks.manifest (was per-installer
# .sh files globbed via 50/56-install-*.sh). The fast-returning backgrounded hooks
# (episodic-capture, evaluator, resume-sessionstart) deliberately use a bare ` &`
# and self-manage output; only the potentially-long-running ones must carry the redirect.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$HERE/../../hooks.manifest"

[[ -r "$MANIFEST" ]] || { echo "FAIL: hooks.manifest not found at $MANIFEST"; exit 1; }

# The command column of every manifest row (strip comments/blanks, take field 3).
commands="$(grep -vE '^\s*(#|$)' "$MANIFEST" | awk -F'|' '{print $3}')"

# 1. Any backgrounded command that redirects must use the COMPLETE `>/dev/null 2>&1 &`
#    form — catch a truncated/partial redirect (e.g. `>/dev/null &` with stderr leaking).
bad=""
while IFS= read -r cmd; do
  [[ -z "$cmd" ]] && continue
  # backgrounded (ends with &) AND mentions a redirect fragment
  if [[ "$cmd" == *"&" ]] && { [[ "$cmd" == *">/dev/null"* ]] || [[ "$cmd" == *"2>&1"* ]]; }; then
    [[ "$cmd" == *">/dev/null 2>&1 &" ]] || bad+="$cmd"$'\n'
  fi
done <<< "$commands"
if [[ -n "$bad" ]]; then
  echo "FAIL: backgrounded hook(s) with an incomplete stdout/stderr redirect:"
  printf '  %s\n' "$bad"
  exit 1
fi

# 2. The known long-running backgrounded hooks MUST be backgrounded WITH the full
#    redirect (the exact regression #101 guarded). Assert each is present in that form.
require() {
  grep -qF "$1" <<< "$commands" || { echo "FAIL: expected a backgrounded+redirected hook matching: $1"; exit 1; }
}
require "cli.py sync >/dev/null 2>&1 &"
require "cli.py sync exit >/dev/null 2>&1 &"
require "hook open-dashboard >/dev/null 2>&1 &"
require "hook backcapture-sweep >/dev/null 2>&1 &"

# 3. Non-vacuity: at least 4 redirect-form backgrounded commands exist.
n="$(grep -cE '>/dev/null 2>&1 &$' <<< "$commands")"
[[ "$n" -ge 4 ]] || { echo "FAIL: expected >=4 redirect-form backgrounded hooks, got $n"; exit 1; }

echo "PASS test_background_hook_redirect"
