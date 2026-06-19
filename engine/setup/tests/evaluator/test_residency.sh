#!/usr/bin/env bash
# np-test: residency | resolved-suggestions.txt default resolves under content root, not engine
# Verify that np-suggestion-resolve.sh and dashboard/build.py route the resolved-
# suggestions ledger through the content resolver (np_content_dir / _content_dir())
# when NP_RESOLVED_SUGGESTIONS is unset -- the same pattern metrics.jsonl already uses.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
NP="$(cd "$SETUP/../.." && pwd)"
RESOLVE="$SETUP/np-suggestion-resolve.sh"
BUILD="$NP/dashboard/build.py"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# ── Test 1: np-suggestion-resolve.sh default lands under NP_CONTENT_DIR, not $NP ──
content_dir="$tmp/content"
mkdir -p "$content_dir/dashboard/data"

NP_CONTENT_DIR="$content_dir" NP_RESOLVE_NO_BUILD=1 bash "$RESOLVE" "Test residency suggestion" >/dev/null
expected_ledger="$content_dir/dashboard/data/resolved-suggestions.txt"
if [[ ! -f "$expected_ledger" ]]; then
  echo "FAIL test_residency (shell): ledger not found under NP_CONTENT_DIR ($expected_ledger)"
  exit 1
fi
grep -q $'^Test residency suggestion\t' "$expected_ledger" \
  || { echo "FAIL test_residency (shell): suggestion text not in ledger"; exit 1; }

# ── Test 2: build.py default resolves resolved-suggestions.txt under _content_dir() ──
# With NP_CONTENT_DIR set and no NP_RESOLVED_SUGGESTIONS, build.py must look in
# $NP_CONTENT_DIR/dashboard/data/resolved-suggestions.txt, not the engine's.
content2="$tmp/content2"
mkdir -p "$content2/dashboard/data"
ledger2="$content2/dashboard/data/resolved-suggestions.txt"
printf 'drop me\n' > "$ledger2"

metrics="$tmp/m.jsonl"
printf '{"session_id":"x","ts":"2026-06-01T10:00:00Z","suggestions":[{"text":"drop me","confidence":0.9}]}\n' > "$metrics"
out_js="$tmp/out.js"

NP_CONTENT_DIR="$content2" python3 "$BUILD" "$metrics" "$out_js" >/dev/null 2>&1

# Parse and assert: the "drop me" suggestion should have been filtered out because
# it appears in the content-dir resolved-suggestions.txt ledger.
python3 - "$out_js" <<'PYEOF'
import json, re, sys
js = open(sys.argv[1]).read()
m = re.search(r'window\.METRICS = (.*?);', js, re.S)
assert m, f"no METRICS in output: {js!r}"
recs = json.loads(m.group(1))
assert len(recs) == 1, f"expected 1 record, got {len(recs)}"
suggs = recs[0].get("suggestions", [])
assert len(suggs) == 0, f"suggestion from content-dir ledger not filtered: {suggs}"
PYEOF

echo "PASS test_residency"
