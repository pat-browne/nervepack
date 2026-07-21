#!/usr/bin/env bash
# Contract test for np-doctor.sh. Verifies: core MUST checks (llm-cli via a stub
# backend, git-sync, toggles) pass on a healthy install; adapter capabilities are
# verified by running the adapter.json verify commands; a missing MUST adapter
# capability fails (exit non-zero); a SHOULD marked 'unsupported' warns but passes.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
DOCTOR="$SETUP/np-doctor.sh"
CAPS="$SETUP/../onboard/capabilities.json"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# healthy temp repo with an origin remote (git-sync MUST)
repo="$tmp/np"; mkdir -p "$repo"
( cd "$repo" && git init -q && git remote add origin https://example.com/x.git \
  && git -c user.email=t@t -c user.name=t commit -qm init --allow-empty )

# stub backend so np-llm.sh complete returns text (llm-cli MUST)
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null; printf 'ok'
STUB
chmod +x "$tmp/claude"

doctor() { NP_DIR="$repo" NP_CAPABILITIES="$CAPS" NP_ADAPTER="$1" CLAUDE_BIN="$tmp/claude" bash "$DOCTOR"; }

# Case A: adapter wires every adapter-capability with a passing verify -> exit 0.
cat > "$tmp/ok.json" <<'JSON'
{ "host":"test", "capabilities": {
  "knowledge":{"status":"wired","verify":"true"},
  "session-start":{"status":"wired","verify":"true"},
  "session-end-capture":{"status":"wired","verify":"true"},
  "session-end-flush":{"status":"wired","verify":"true"},
  "scheduled-maint":{"status":"wired","verify":"true"} } }
JSON
set +e; outA="$(doctor "$tmp/ok.json" 2>&1)"; rcA=$?; set -e
[[ $rcA -eq 0 ]] || { echo "FAIL: healthy install should exit 0; got $rcA"; echo "$outA"; exit 1; }
echo "$outA" | grep -q 'llm-cli' || { echo "FAIL: report missing llm-cli line"; exit 1; }
echo "$outA" | grep -qi 'knowledge.*PASS' || { echo "FAIL: knowledge should PASS via adapter verify"; echo "$outA"; exit 1; }

# Case B: knowledge (a MUST) has no adapter entry -> MISSING -> exit non-zero.
cat > "$tmp/bad.json" <<'JSON'
{ "host":"test", "capabilities": { "session-start":{"status":"wired","verify":"true"} } }
JSON
set +e; outB="$(doctor "$tmp/bad.json" 2>&1)"; rcB=$?; set -e
[[ $rcB -ne 0 ]] || { echo "FAIL: missing MUST (knowledge) should exit non-zero"; echo "$outB"; exit 1; }
echo "$outB" | grep -qi 'knowledge.*MISSING' || { echo "FAIL: knowledge should report MISSING"; echo "$outB"; exit 1; }

# Case C: a SHOULD marked unsupported -> UNSUPPORTED, still exit 0 (knowledge wired).
cat > "$tmp/unsup.json" <<'JSON'
{ "host":"test", "capabilities": {
  "knowledge":{"status":"wired","verify":"true"},
  "session-start":{"status":"unsupported","verify":""},
  "session-end-capture":{"status":"unsupported","verify":""},
  "session-end-flush":{"status":"unsupported","verify":""},
  "scheduled-maint":{"status":"unsupported","verify":""} } }
JSON
set +e; outC="$(doctor "$tmp/unsup.json" 2>&1)"; rcC=$?; set -e
[[ $rcC -eq 0 ]] || { echo "FAIL: unsupported SHOULDs must not fail the doctor; got $rcC"; echo "$outC"; exit 1; }
echo "$outC" | grep -qi 'session-start.*UNSUPPORTED' || { echo "FAIL: should report UNSUPPORTED"; echo "$outC"; exit 1; }

# Case D: a verify using the idiomatic `producer | grep -q PAT` form must PASS.
# `grep -q` closes the pipe on first match, so the producer takes SIGPIPE (141);
# the doctor must not let its `pipefail` turn that into a FAIL. `seq` overruns the
# pipe buffer and matches on line 1, so this deterministically SIGPIPEs the
# producer (regression guard for the launchctl/crontab scheduled-maint verifies).
cat > "$tmp/pipe.json" <<'JSON'
{ "host":"test", "capabilities": {
  "knowledge":{"status":"wired","verify":"seq 100000 | grep -q 1"},
  "session-start":{"status":"wired","verify":"true"},
  "session-end-capture":{"status":"wired","verify":"true"},
  "session-end-flush":{"status":"wired","verify":"true"},
  "scheduled-maint":{"status":"wired","verify":"seq 100000 | grep -q 1"} } }
JSON
set +e; outD="$(doctor "$tmp/pipe.json" 2>&1)"; rcD=$?; set -e
[[ $rcD -eq 0 ]] || { echo "FAIL: 'producer | grep -q' verify must not SIGPIPE-fail under pipefail; got $rcD"; echo "$outD"; exit 1; }
echo "$outD" | grep -qi 'knowledge.*PASS' || { echo "FAIL: pipe-form verify should PASS"; echo "$outD"; exit 1; }

# helper: run doctor with a specific CLAUDE_SETTINGS file (uses ok.json adapter)
doctor_hooks() { CLAUDE_SETTINGS="$1" NP_DIR="$repo" NP_CAPABILITIES="$CAPS" NP_ADAPTER="$tmp/ok.json" CLAUDE_BIN="$tmp/claude" bash "$DOCTOR"; }

# Case E: no settings.json → hook-scripts PASS with advisory note.
set +e; outE="$(CLAUDE_SETTINGS="$tmp/nonexistent.json" NP_DIR="$repo" NP_CAPABILITIES="$CAPS" NP_ADAPTER="$tmp/ok.json" CLAUDE_BIN="$tmp/claude" bash "$DOCTOR" 2>&1)"; rcE=$?; set -e
[[ $rcE -eq 0 ]] || { echo "FAIL: absent settings.json should not fail doctor; got $rcE"; echo "$outE"; exit 1; }
echo "$outE" | grep -qi 'hook-scripts.*PASS' || { echo "FAIL: absent settings.json should report hook-scripts PASS"; echo "$outE"; exit 1; }

# Case F: settings.json references scripts that all exist → hook-scripts PASS.
# Use a stub in $tmp (guaranteed resolvable on all platforms, including Windows CI).
printf '#!/usr/bin/env bash\n' > "$tmp/real-guard.sh"
chmod +x "$tmp/real-guard.sh"
cat > "$tmp/hooks-ok.json" <<EOF
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"$tmp/real-guard.sh"}]}]}}
EOF
set +e; outF="$(doctor_hooks "$tmp/hooks-ok.json" 2>&1)"; rcF=$?; set -e
[[ $rcF -eq 0 ]] || { echo "FAIL: all-existing hook scripts should exit 0; got $rcF"; echo "$outF"; exit 1; }
echo "$outF" | grep -qi 'hook-scripts.*PASS' || { echo "FAIL: all-existing hook scripts should report PASS"; echo "$outF"; exit 1; }

# Case G: settings.json has two missing scripts and one real one → hook-scripts FAIL in report.
# Doctor still exits 0 (hook-scripts is SHOULD, not MUST).
cat > "$tmp/hooks-bad.json" <<EOF
{"hooks":{
  "PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"$tmp/missing-guard.sh"}]}],
  "SessionStart":[{"matcher":"","hooks":[
    {"type":"command","command":"$SETUP/np-doctor.sh"},
    {"type":"command","command":"$tmp/another-gone.sh"}
  ]}]
}}
EOF
set +e; outG="$(doctor_hooks "$tmp/hooks-bad.json" 2>&1)"; rcG=$?; set -e
[[ $rcG -eq 0 ]] || { echo "FAIL: missing hook scripts are SHOULD — doctor must still exit 0; got $rcG"; echo "$outG"; exit 1; }
echo "$outG" | grep -qi 'hook-scripts.*FAIL' || { echo "FAIL: missing hook scripts should report FAIL on hook-scripts line"; echo "$outG"; exit 1; }
echo "$outG" | grep -qi 'missing-guard' || { echo "FAIL: report should name missing-guard.sh"; echo "$outG"; exit 1; }
echo "$outG" | grep -qi 'another-gone' || { echo "FAIL: report should name another-gone.sh"; echo "$outG"; exit 1; }

# Case H: scheduled-auth-token core check — WARN when no token file, PASS once stored.
tokfile="$tmp/claude-oauth-token"
set +e; outH="$(NP_CLAUDE_TOKEN_FILE="$tokfile" doctor "$tmp/ok.json" 2>&1)"; rcH=$?; set -e
[[ $rcH -eq 0 ]] || { echo "FAIL: missing scheduled-auth-token (SHOULD) must not fail doctor; got $rcH"; echo "$outH"; exit 1; }
echo "$outH" | grep -qi 'scheduled-auth-token.*WARN' || { echo "FAIL: expected scheduled-auth-token WARN when unset"; echo "$outH"; exit 1; }
printf 'dummy' > "$tokfile"; date -u +%Y-%m-%d > "$tokfile.issued"
set +e; outH2="$(NP_CLAUDE_TOKEN_FILE="$tokfile" doctor "$tmp/ok.json" 2>&1)"; rcH2=$?; set -e
[[ $rcH2 -eq 0 ]] || { echo "FAIL: fresh scheduled-auth-token should exit 0; got $rcH2"; echo "$outH2"; exit 1; }
echo "$outH2" | grep -qi 'scheduled-auth-token.*PASS' || { echo "FAIL: expected scheduled-auth-token PASS once stored"; echo "$outH2"; exit 1; }

echo "PASS test_doctor"
