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

echo "PASS test_doctor"
