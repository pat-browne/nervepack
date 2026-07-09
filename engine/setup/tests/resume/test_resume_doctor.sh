#!/usr/bin/env bash
# np-test: resume|doctor
# Task 6: the `resume-pointer` capability (engine/onboard/capabilities.json,
# core_check arm in np-doctor.sh). PASS iff np-resume-write.sh is executable
# (it is, in this checkout) AND both np-resume-sessionstart.sh (SessionStart)
# and np-resume-recall.sh (UserPromptSubmit) are registered in CLAUDE_SETTINGS.
# Otherwise WARN with a fix hint. Hermetic: temp HOME (no real adapter.json /
# toggles), temp CLAUDE_SETTINGS fixtures — never touches the real
# ~/.claude/settings.json or ~/.config/nervepack.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../../../.." && pwd)"   # tests/resume -> setup -> engine -> repo root
DOCTOR="$NP/engine/setup/np-doctor.sh"

fail() { echo "FAIL: $*"; exit 1; }

command -v jq >/dev/null || { echo "PASS test_resume_doctor (skipped — jq missing)"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"; mkdir -p "$HOME"

doctor() { CLAUDE_SETTINGS="$1" bash "$DOCTOR" 2>&1 || true; }

# === 1. Both hooks registered (right event each) -> resume-pointer PASS. ===
cat > "$tmp/settings-ok.json" <<'JSON'
{"hooks":{
  "SessionStart":[{"matcher":"","hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/np-resume-sessionstart.sh &"}]}],
  "UserPromptSubmit":[{"matcher":"","hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/np-resume-recall.sh"}]}]
}}
JSON
outA="$(doctor "$tmp/settings-ok.json")"
echo "$outA" | grep -qE 'resume-pointer +PASS$' \
  || fail "both hooks registered should report resume-pointer PASS: $(echo "$outA" | grep resume-pointer)"

echo "PASS: both hooks registered -> resume-pointer PASS"

# === 2. Hooks absent entirely -> WARN (not PASS), with a fix hint. ===
cat > "$tmp/settings-empty.json" <<'JSON'
{"hooks":{}}
JSON
outB="$(doctor "$tmp/settings-empty.json")"
echo "$outB" | grep -qE 'resume-pointer +PASS$' \
  && fail "absent hooks must not PASS resume-pointer: $(echo "$outB" | grep resume-pointer)"
echo "$outB" | grep -qE 'resume-pointer +WARN' \
  || fail "absent hooks should report resume-pointer WARN: $(echo "$outB" | grep resume-pointer)"
echo "$outB" | grep 'resume-pointer' | grep -qi '61-install-resume-hook.sh' \
  || fail "resume-pointer WARN should hint at 61-install-resume-hook.sh: $(echo "$outB" | grep resume-pointer)"

echo "PASS: no hooks registered -> resume-pointer WARN with fix hint"

# === 3. Non-vacuity: only ONE of the two hooks present -> still not PASS. ===
cat > "$tmp/settings-partial.json" <<'JSON'
{"hooks":{
  "SessionStart":[{"matcher":"","hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/np-resume-sessionstart.sh &"}]}]
}}
JSON
outC="$(doctor "$tmp/settings-partial.json")"
echo "$outC" | grep -qE 'resume-pointer +PASS$' \
  && fail "one missing hook must not PASS resume-pointer: $(echo "$outC" | grep resume-pointer)"
echo "$outC" | grep -qE 'resume-pointer +WARN' \
  || fail "one missing hook should report resume-pointer WARN: $(echo "$outC" | grep resume-pointer)"

echo "PASS: only one hook registered -> resume-pointer still WARN (non-vacuous)"

# === 4. Writer not executable -> WARN, even with BOTH hooks registered. ===
# Point NP_DIR at a throwaway tree whose np-resume-write.sh exists but is NOT
# executable, so the ONLY unmet condition is the writer-executable half. Settings
# still register both hooks, isolating that branch.
altnp="$tmp/altnp"; mkdir -p "$altnp/engine/setup"
printf '#!/usr/bin/env bash\n' > "$altnp/engine/setup/np-resume-write.sh"
chmod -x "$altnp/engine/setup/np-resume-write.sh"
# NP_DIR override also redirects the default capabilities.json path, so pin
# NP_CAPABILITIES back to the real contract (only the writer path should change).
outD="$(NP_DIR="$altnp" NP_CAPABILITIES="$NP/engine/onboard/capabilities.json" doctor "$tmp/settings-ok.json")"
echo "$outD" | grep -qE 'resume-pointer +PASS$' \
  && fail "non-executable writer must not PASS resume-pointer: $(echo "$outD" | grep resume-pointer)"
echo "$outD" | grep 'resume-pointer' | grep -qi 'not executable' \
  || fail "non-executable writer should WARN about the writer: $(echo "$outD" | grep resume-pointer)"

echo "PASS: writer not executable -> resume-pointer WARN (writer branch)"

echo "PASS test_resume_doctor"
