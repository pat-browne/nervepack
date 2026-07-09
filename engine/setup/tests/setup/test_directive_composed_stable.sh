#!/usr/bin/env bash
# np-test: nervepack-session-directive | composed stability (engine + content fragment)
# The engine directive table no longer hardcodes personal/domain routing rows; those
# live in $NP_CONTENT_DIR/directive-routing.md, appended fail-open by the emitter
# script. The COMPOSED output (engine + fragment, when present) must stay byte-stable
# across runs — same invariant 11 as the engine-only directive, extended to cover the
# fragment-present case.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; SETUP="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
printf '## Personal routing\n| Trigger | Skill |\n' > "$tmp/directive-routing.md"

# (a) fragment absent -> engine directive only, stable across two runs, and the
# engine table no longer hardcodes a personal/domain row.
a1="$(NP_CONTENT_DIR="$tmp/none" bash "$SETUP/nervepack-session-directive.sh")"
a2="$(NP_CONTENT_DIR="$tmp/none" bash "$SETUP/nervepack-session-directive.sh")"
[[ "$a1" == "$a2" ]] || { echo "FAIL: engine-only output not byte-stable"; exit 1; }
echo "$a1" | grep -q "np-kb-chrome" && { echo "FAIL: personal row still hardcoded in engine directive"; exit 1; }

# (b) fragment present -> appended, still stable
b1="$(NP_CONTENT_DIR="$tmp" bash "$SETUP/nervepack-session-directive.sh")"
b2="$(NP_CONTENT_DIR="$tmp" bash "$SETUP/nervepack-session-directive.sh")"
[[ "$b1" == "$b2" ]] || { echo "FAIL: composed output not byte-stable"; exit 1; }
echo "$b1" | grep -q "Personal routing" || { echo "FAIL: content fragment not appended"; exit 1; }

echo "PASS test_directive_composed_stable"
