#!/usr/bin/env bash
# Test for 70-install-memory-launchd.sh (macOS scheduled-maint path). Runs on Linux
# CI via NP_LAUNCHD_FORCE + a stub launchctl + hermetic dirs: asserts it writes the
# six LaunchAgent plists (well-formed XML, correct label/time/target), loads each
# via launchctl, is idempotent, and refuses on a non-Darwin host without the force.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
INSTALLER="$SETUP/70-install-memory-launchd.sh"

bash -n "$INSTALLER" || { echo "FAIL: syntax error in installer"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
la="$tmp/LaunchAgents"; logs="$tmp/logs"; calls="$tmp/launchctl-calls"

# stub launchctl on PATH — records its argv so we can assert load/unload happened
mkdir -p "$tmp/bin"
cat > "$tmp/bin/launchctl" <<STUB
#!/usr/bin/env bash
echo "\$*" >> "$calls"
exit 0
STUB
chmod +x "$tmp/bin/launchctl"

# stub uname so the non-Darwin refusal path (case 6) can be exercised on a real Mac
# (forced runs set NP_LAUNCHD_FORCE and ignore the OS check, so this is inert for them)
cat > "$tmp/bin/uname" <<'STUB'
#!/usr/bin/env bash
echo Linux
STUB
chmod +x "$tmp/bin/uname"

run() { NP_LAUNCHD_FORCE=1 NP_LAUNCHAGENTS_DIR="$la" NP_LAUNCHD_LOG_DIR="$logs" \
        NP_LAUNCHD_SETUP_DIR="$SETUP" PATH="$tmp/bin:$PATH" bash "$INSTALLER"; }

# --- run it ---
run >/dev/null

# 1. exactly the six expected agents exist
for j in memory-promote episodic-maintain aggregate-metrics skill-maintain refine compact; do
  [[ -f "$la/com.nervepack.$j.plist" ]] || { echo "FAIL: missing plist for $j"; exit 1; }
done
n="$(find "$la" -name '*.plist' | wc -l | tr -d '[:space:]')"
[[ "$n" == 6 ]] || { echo "FAIL: expected 6 plists, got $n"; exit 1; }

# 2. each plist is well-formed XML (parse with python stdlib)
for p in "$la"/*.plist; do
  python3 -c "import sys,xml.dom.minidom as m; m.parse(sys.argv[1])" "$p" \
    || { echo "FAIL: malformed plist $p"; exit 1; }
done

# 3. content is correct: label, schedule, and the script it execs
grep -q '<string>com.nervepack.skill-maintain</string>' "$la/com.nervepack.skill-maintain.plist" \
  || { echo "FAIL: skill-maintain label wrong"; exit 1; }
grep -q '<key>Hour</key><integer>9</integer>' "$la/com.nervepack.skill-maintain.plist" \
  || { echo "FAIL: skill-maintain hour wrong"; exit 1; }
grep -q '<key>Minute</key><integer>15</integer>' "$la/com.nervepack.skill-maintain.plist" \
  || { echo "FAIL: skill-maintain minute wrong"; exit 1; }
grep -q "75-skill-maintain.sh" "$la/com.nervepack.skill-maintain.plist" \
  || { echo "FAIL: skill-maintain target wrong"; exit 1; }
grep -q '<key>Hour</key><integer>8</integer>' "$la/com.nervepack.memory-promote.plist" \
  || { echo "FAIL: memory-promote hour wrong"; exit 1; }

# 4. launchctl was invoked to load each agent (-w load)
[[ "$(grep -c 'load -w' "$calls")" == 6 ]] || { echo "FAIL: expected 6 launchctl loads, got $(grep -c 'load -w' "$calls" 2>/dev/null)"; exit 1; }

# 5. idempotent: a second run still leaves exactly six plists (no duplicates)
run >/dev/null
n2="$(find "$la" -name '*.plist' | wc -l | tr -d '[:space:]')"
[[ "$n2" == 6 ]] || { echo "FAIL: not idempotent — $n2 plists after second run"; exit 1; }

# 6. on a non-Darwin host WITHOUT the force, it refuses and writes nothing
la2="$tmp/LA2"
out="$(PATH="$tmp/bin:$PATH" NP_LAUNCHAGENTS_DIR="$la2" NP_LAUNCHD_LOG_DIR="$tmp/logs2" NP_LAUNCHD_SETUP_DIR="$SETUP" \
       bash "$INSTALLER" 2>&1)" && { echo "FAIL: installer should exit non-zero on non-Darwin"; exit 1; }
[[ "$out" == *"macOS path"* ]] || { echo "FAIL: missing OS-mismatch message"; exit 1; }
[[ -d "$la2" ]] && { echo "FAIL: wrote LaunchAgents dir on a non-Darwin host"; exit 1; }

# 7. the shipped macOS adapter example is valid JSON and uses the launchd verify
ADAPTER="$SETUP/../onboard/adapters/claude-code-macos.example.json"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert 'launchctl' in d['capabilities']['scheduled-maint']['verify']" "$ADAPTER" \
  || { echo "FAIL: macOS adapter example invalid or missing launchd verify"; exit 1; }

echo "PASS test_install_memory_launchd"
