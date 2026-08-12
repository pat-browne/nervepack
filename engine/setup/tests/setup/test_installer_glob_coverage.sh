#!/usr/bin/env bash
# np-test: installer-glob-coverage | happy
# Two coverage invariants, post phase-13 (hook installers consolidated into
# engine/setup/hooks.manifest, driven by `cli.py setup install-hooks`):
#
#   A. The remaining-installer glob in np_onboard.py AND np_sync.py (phase 17:
#      40-sync-nervepack.sh retired) still picks up the non-hook 5x/6x installers
#      (58-install-mcp.sh,
#      62-install-scheduled-auth-token.sh) and still EXCLUDES the
#      platform-specific 70-install-memory-* installers.
#   B. Hook coverage now lives in hooks.manifest: every `cli.py hook <name>`
#      row maps to a real handler in cli.py's _HOOKS, and every _HOOKS handler
#      appears in the manifest (no dead rows, no orphan handlers).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
MANIFEST="$SETUP/hooks.manifest"
CLI="$SETUP/../nervepack_engine/cli.py"

fail() { echo "FAIL test_installer_glob_coverage: $*"; exit 1; }

# --- A. remaining-installer glob still covers non-hook 5x/6x, excludes 70 ---
# Sanity: a remaining non-hook installer must exist, else part A is vacuous.
[[ -e "$SETUP/58-install-mcp.sh" ]] \
  || fail "58-install-mcp.sh missing — remaining-installer fixture assumption broken"

# np_onboard stays in engine/setup; np_sync was relocated into engine/nervepack_engine
# (phase 20b-2) — carry full paths so each resolves at its real location.
for path in "$SETUP/np_onboard.py" "$SETUP/../nervepack_engine/np_sync.py"; do
  driver="$(basename "$path")"
  [[ -e "$path" ]] || fail "$driver not found at $path"
  glob="$(grep -oE '(\[[0-9]+\]|[0-9])\[0-9\]-install-\*\.sh' "$path" | head -1)"
  [[ -n "$glob" ]] || fail "$driver: no remaining-installer glob (NN-install-*.sh) found"

  matched=""
  for f in $SETUP/$glob; do
    [[ -e "$f" ]] && matched+="$(basename "$f")"$'\n'
  done

  grep -q '^58-install-mcp\.sh$' <<<"$matched" \
    || fail "$driver glob '$glob' does not pick up 58-install-mcp.sh (remaining non-hook installer)"
  grep -q '70-install-memory' <<<"$matched" \
    && fail "$driver glob '$glob' wrongly matches the platform-specific 70-install-memory-* installer"
  echo "PASS: $driver glob '$glob' covers 58-install-mcp.sh, excludes 70-install-memory-*"
done

# --- B. hooks.manifest <-> cli.py _HOOKS bidirectional coverage ---
[[ -r "$MANIFEST" ]] || fail "hooks.manifest not found at $MANIFEST"

# Hook names referenced in the manifest (dedup).
manifest_names="$(grep -oE 'cli\.py hook [a-z0-9_-]+' "$MANIFEST" | awk '{print $3}' | sort -u)"
[[ -n "$manifest_names" ]] || fail "no 'cli.py hook <name>' rows found in the manifest"

# Handler names registered in cli.py's _HOOKS dict (the keys), via Python.
handler_names="$(python3 - "$CLI" <<'PY'
import importlib.util, os, sys
cli_path = sys.argv[1]
engine = os.path.normpath(os.path.join(os.path.dirname(cli_path), ".."))
setup = os.path.join(engine, "setup")
for p in (engine, setup):
    if p not in sys.path:
        sys.path.insert(0, p)
spec = importlib.util.spec_from_file_location("nervepack_engine.cli", cli_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("\n".join(sorted(mod._HOOKS)))
PY
)"
# Strip CR: on Windows, Python print() emits CRLF, so each handler name would
# carry a trailing \r and never match the LF-only manifest names below.
handler_names="${handler_names//$'\r'/}"
[[ -n "$handler_names" ]] || fail "could not read _HOOKS from cli.py"

# Every manifest hook name must have a handler.
while IFS= read -r name; do
  [[ -z "$name" ]] && continue
  grep -qx "$name" <<<"$handler_names" \
    || fail "manifest hook '$name' has no handler in cli.py _HOOKS"
done <<<"$manifest_names"

# Every _HOOKS handler must appear in the manifest (no orphan handler).
while IFS= read -r name; do
  [[ -z "$name" ]] && continue
  grep -qx "$name" <<<"$manifest_names" \
    || fail "cli.py _HOOKS handler '$name' is not registered by any hooks.manifest row"
done <<<"$handler_names"

echo "PASS: hooks.manifest and cli.py _HOOKS are in bidirectional coverage"

# --- C. lesson-guard PreToolUse matcher coverage (issue #152 regression) ---
# Phase 2 (non-Bash tool_name matching) only ever runs for a tool name that
# Claude Code was told to invoke this hook for -- a matcher missing from
# hooks.manifest silently means "never fires," with no other signal. Pin the
# full expected matcher set here so a future edit can't quietly drop one.
lesson_guard_matchers="$(grep -E '^PreToolUse\|[^|]*\|.*hook lesson-guard' "$MANIFEST" \
  | awk -F'|' '{print $2}' | sort -u)"
[[ -n "$lesson_guard_matchers" ]] || fail "no PreToolUse lesson-guard rows found in the manifest"

for expected in Bash Read Edit Write Skill 'mcp__.*'; do
  grep -qxF "$expected" <<<"$lesson_guard_matchers" \
    || fail "hooks.manifest is missing a PreToolUse lesson-guard row for matcher '$expected' (issue #152)"
done
echo "PASS: hooks.manifest registers lesson-guard for Bash/Read/Edit/Write/Skill/mcp__.* (issue #152)"

echo "PASS test_installer_glob_coverage"
