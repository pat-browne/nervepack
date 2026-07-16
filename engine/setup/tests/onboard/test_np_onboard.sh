#!/usr/bin/env bash
# np-test: np-onboard | happy
# The full-onboard orchestrator (np-onboard.sh): in a hermetic HOME with stubbed
# claude/crontab, it links skills, runs the 5x hook installers (so the lifecycle
# hooks land in settings.json), installs the scheduler, and ends by running the
# doctor. Fail-soft: a failing step doesn't abort the run.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
ONBOARD="$SETUP/np-onboard.sh"

fail() { echo "FAIL: $*"; exit 1; }
[[ -f "$ONBOARD" ]] || fail "np-onboard.sh not found at $ONBOARD"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
home="$tmp/home"; mkdir -p "$home/.claude" "$tmp/bin"
export HOME="$home"
export CLAUDE_SETTINGS="$home/.claude/settings.json"; echo '{}' > "$CLAUDE_SETTINGS"

# Stubs: claude (58-install-mcp + the doctor's llm smoke) and crontab (the scheduler
# on Linux) — so the run never touches the real host.
cat > "$tmp/bin/claude" <<'S'
#!/usr/bin/env bash
[[ "$1" == "mcp" ]] && exit 0
printf 'ok'   # any other invocation (e.g. the llm smoke) returns non-empty text
exit 0
S
cat > "$tmp/bin/crontab" <<'S'
#!/usr/bin/env bash
[[ "${1:-}" == "-l" ]] && exit 0
cat >/dev/null
S
chmod +x "$tmp/bin/claude" "$tmp/bin/crontab"
export PATH="$tmp/bin:$PATH"

out="$(bash "$ONBOARD" 2>&1)" && rc=0 || rc=$?

# --- the run reached every phase (fail-soft, so exit code is the doctor's) ---
grep -q '── 30-link-skills.sh' <<<"$out" || fail "skills-link step didn't run; output:\n$out"
grep -qE '── 5[0-9]-install-.*\.sh' <<<"$out" || fail "no 5x hook installer ran; output:\n$out"
grep -q '── np-doctor.sh' <<<"$out" || fail "doctor step didn't run; output:\n$out"
echo "  OK: onboard ran skills-link + 5x hooks + doctor (rc=$rc)"

# --- the lifecycle hooks actually landed in settings.json (real side effect) ---
command -v jq >/dev/null || { echo "PASS test_np_onboard (jq missing — skipped hook assertions)"; exit 0; }
reg() { jq -r "[.. | .command? // empty | select(test(\"$1\"))] | length" "$CLAUDE_SETTINGS"; }
[[ "$(reg 'cli.py hook lesson-recall')" -ge 1 ]] || fail "lesson-recall not registered after onboard"
[[ "$(reg 'cli.py hook lesson-guard')"  -ge 1 ]] || fail "lesson-guard not registered after onboard"
[[ "$(reg 'nervepack-session-directive.sh')" -ge 1 ]] || fail "session directive not registered after onboard"
echo "  OK: lesson-recall + lesson-guard + directive registered in settings.json"

# --- idempotent: a second run doesn't duplicate the recall hook ---
bash "$ONBOARD" >/dev/null 2>&1 || true
[[ "$(reg 'cli.py hook lesson-recall')" == "1" ]] || fail "onboard not idempotent: lesson-recall count = $(reg 'cli.py hook lesson-recall')"
echo "  OK: re-run is idempotent"

echo "PASS test_np_onboard"
