#!/usr/bin/env bash
# Test for 70-install-memory-schtasks.sh (native-Windows scheduled-maint path; runs
# under Git-for-Windows bash). Runs on Linux CI via NP_SCHTASKS_FORCE + a stub
# schtasks + hermetic dirs: asserts it creates the six nervepack scheduled tasks with
# the right names, schedules (daily 71/72/73/75; weekly Sun refine, weekly Wed
# compact — the authoritative cron cadence), and a Git-bash task action; is idempotent
# (/F replace, never a duplicate); and refuses on a non-Windows host without the force.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
INSTALLER="$SETUP/70-install-memory-schtasks.sh"

bash -n "$INSTALLER" || { echo "FAIL: syntax error in installer"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
calls="$tmp/schtasks-calls"

# stub schtasks on PATH — records its argv so we can assert each task was created
mkdir -p "$tmp/bin"
cat > "$tmp/bin/schtasks" <<STUB
#!/usr/bin/env bash
echo "\$*" >> "$calls"
exit 0
STUB
chmod +x "$tmp/bin/schtasks"

# stub uname so the non-Windows refusal path can be exercised on a real Mingw box too
cat > "$tmp/bin/uname" <<'STUB'
#!/usr/bin/env bash
echo Linux
STUB
chmod +x "$tmp/bin/uname"

run() { NP_SCHTASKS_FORCE=1 NP_SCHTASKS_SETUP_DIR="$SETUP" \
        PATH="$tmp/bin:$PATH" bash "$INSTALLER"; }

# --- run it ---
run >/dev/null

# 1. exactly the six expected tasks were created (one //Create call each)
created="$(grep -c '//Create' "$calls" 2>/dev/null || echo 0)"
[[ "$created" == 6 ]] || { echo "FAIL: expected 6 task creations, got $created"; cat "$calls"; exit 1; }

# 2. each task is namespaced under the nervepack\ task folder (verify grep target)
for j in memory-promote episodic-maintain aggregate-metrics skill-maintain refine compact; do
  grep -qF "nervepack\\$j" "$calls" || { echo "FAIL: missing task nervepack\\$j"; cat "$calls"; exit 1; }
done

# 3. schedules are correct: dailies at their minute, weeklies on the right weekday
grep -E "nervepack\\\\memory-promote.*//SC DAILY.*//ST 08:00" "$calls" >/dev/null \
  || { echo "FAIL: memory-promote not DAILY 08:00"; cat "$calls"; exit 1; }
grep -E "nervepack\\\\skill-maintain.*//SC DAILY.*//ST 09:15" "$calls" >/dev/null \
  || { echo "FAIL: skill-maintain not DAILY 09:15"; cat "$calls"; exit 1; }
grep -E "nervepack\\\\refine.*//SC WEEKLY.*//D SUN.*//ST 09:30" "$calls" >/dev/null \
  || { echo "FAIL: refine not WEEKLY SUN 09:30"; cat "$calls"; exit 1; }
grep -E "nervepack\\\\compact.*//SC WEEKLY.*//D WED.*//ST 10:00" "$calls" >/dev/null \
  || { echo "FAIL: compact not WEEKLY WED 10:00"; cat "$calls"; exit 1; }

# 4. the task action runs the .sh body through bash (Git-for-Windows) and forces replace
grep -E "cli.py cron memory-promote" "$calls" >/dev/null \
  || { echo "FAIL: memory-promote action does not reference its cli.py dispatch"; exit 1; }
grep -E "//TR .*bash" "$calls" >/dev/null \
  || { echo "FAIL: task action does not invoke bash"; exit 1; }
[[ "$(grep -c '//F' "$calls")" == 6 ]] || { echo "FAIL: not every task uses //F (idempotent replace)"; exit 1; }

# 5. idempotent: a second run still creates exactly six (the /F replace, no dupes)
: > "$calls"
run >/dev/null
created2="$(grep -c '//Create' "$calls" 2>/dev/null || echo 0)"
[[ "$created2" == 6 ]] || { echo "FAIL: not idempotent — $created2 creations on second run"; exit 1; }

# 6. on a non-Windows host WITHOUT the force, it refuses and creates nothing
: > "$calls"
out="$(PATH="$tmp/bin:$PATH" NP_SCHTASKS_SETUP_DIR="$SETUP" bash "$INSTALLER" 2>&1)" \
  && { echo "FAIL: installer should exit non-zero on a non-Windows host"; exit 1; }
[[ "$out" == *"Windows path"* ]] || { echo "FAIL: missing OS-mismatch message"; exit 1; }
[[ -s "$calls" ]] && { echo "FAIL: created a task on a non-Windows host"; exit 1; }

# 7. the shipped Windows adapter example is valid JSON and uses the schtasks verify
ADAPTER="$SETUP/../onboard/adapters/claude-code-windows.example.json"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert 'schtasks' in d['capabilities']['scheduled-maint']['verify']" "$ADAPTER" \
  || { echo "FAIL: Windows adapter example invalid or missing schtasks verify"; exit 1; }

echo "PASS test_install_memory_schtasks"
