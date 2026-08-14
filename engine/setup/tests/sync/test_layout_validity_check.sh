#!/usr/bin/env bash
# np-test: sync | happy+failure
# np_sync._layout_validity_check validates every content layer's
# .nervepack/layout.json on each real sync pass (nervepack#244), reusing the same
# np_layout.resolve check np_doctor runs for the layer-layout capability. A corrupt
# manifest must print a stderr note naming the layer, and must NOT touch the
# parity-locked status output -- the check is advisory only.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
command -v cygpath >/dev/null 2>&1 && tmp="$(cygpath -m "$tmp")"
export HOME="$tmp"; mkdir -p "$tmp/.config/nervepack" "$tmp/notgit" "$tmp/team/.nervepack"
export NP_TOGGLES_CONF="$S/toggles.conf"
printf 'team=on\n' > "$tmp/.config/nervepack/toggles.local"
export NP_TOGGLES_LOCAL="$tmp/.config/nervepack/toggles.local"
export NP_TEAM_DIR="$tmp/team"
export NP_SYNC_TARGET="$tmp/notgit"
export NP_SYNC_STATUS="$tmp/status"
export NP_SYNC_STAMP="$tmp/stamp"
PY="$S/../nervepack_engine/np_sync.py"

# (1) A valid manifest: no stderr note, and the normal not-a-git status still writes.
cat > "$tmp/team/.nervepack/layout.json" <<'EOF'
{"schema": 1, "routes": {"skill": {"path": "skills/{name}/SKILL.md"}}}
EOF
out1="$(python3 "$PY" exit 2>"$tmp/err1")"
[[ "$out1" == *"not a git repo"* ]] || { echo "FAIL: expected the real not-a-git outcome, got: $out1"; exit 1; }
grep -q "layout manifest invalid" "$tmp/err1" && { echo "FAIL: valid manifest reported invalid: $(cat "$tmp/err1")"; exit 1; }
shape1="${out1#*— }"

# (2) A corrupt manifest: a stderr note names the layer, and the status outcome is
# unaffected (modulo the embedded timestamp) -- proving the check is non-fatal.
printf '{not valid json' > "$tmp/team/.nervepack/layout.json"
out2="$(python3 "$PY" exit 2>"$tmp/err2")"
shape2="${out2#*— }"
[[ "$shape2" == "$shape1" ]] || { echo "FAIL: status outcome changed on a corrupt team manifest ($out2 vs $out1)"; exit 1; }
grep -q "layout manifest invalid" "$tmp/err2" || { echo "FAIL: no stderr note for a corrupt manifest: $(cat "$tmp/err2")"; exit 1; }
grep -q "$tmp/team" "$tmp/err2" || { echo "FAIL: stderr note did not name the layer: $(cat "$tmp/err2")"; exit 1; }

echo "PASS test_layout_validity_check"
