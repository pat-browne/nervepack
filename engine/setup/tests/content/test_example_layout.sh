#!/usr/bin/env bash
# Anti-drift contract: the engine must read EVERY layer the canonical example
# skeleton ships (memory/{episodic,playbooks,strategies} + wiki/{topics,concepts}/<x>/
# with co-located sources). If a reader stops resolving a canonical-layout layer,
# this goes red. Zero-dep; runs each reader against a committed fixture via
# NP_CONTENT_DIR. Assertions check real fixture CONTENT (not just "no error"), so a
# reader that silently resolves the wrong path fails here.
#
# The fixture mirrors nervepack-content-example's shape and MUST be updated in
# lockstep if the canonical layout changes.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
REPO="$(cd "$SETUP/../.." && pwd)"
FIX="$SETUP/tests/fixtures/example-layout"
export NP_CONTENT_DIR="$FIX"

command -v jq >/dev/null || { echo "SKIP: jq not available"; exit 0; }

fail() { echo "FAIL: $1"; exit 1; }

# 1. layer resolver maps to memory/<layer>
out="$(bash -c 'source "'"$SETUP/np-layer-lib.sh"'"; np_layer_roots playbooks')"
[ "$out" = "$FIX/memory/playbooks" ] || fail "np_layer_roots playbooks -> [$out], want [$FIX/memory/playbooks]"

# 2. playbook-recall surfaces the fixture playbook body from memory/playbooks
st="$(mktemp -d)"
pr="$(printf '{"session_id":"t1","prompt":"please handle demoword now"}' \
      | EPISODIC_STATE_DIR="$st" bash "$SETUP/playbook-recall.sh" 2>/dev/null || true)"
printf '%s' "$pr" | grep -q 'demo' || fail "playbook-recall did not surface memory/playbooks (out=[$pr])"

# 3. strategy-recall surfaces the fixture strategy from memory/strategies
st2="$(mktemp -d)"
sr="$(printf '{"session_id":"t2","prompt":"please handle demoword now"}' \
      | EPISODIC_STATE_DIR="$st2" bash "$SETUP/strategy-recall.sh" 2>/dev/null || true)"
printf '%s' "$sr" | grep -q 'demo' || fail "strategy-recall did not surface memory/strategies (out=[$sr])"

# 4. episodic-recall surfaces the fixture episodic theme from memory/episodic
st3="$(mktemp -d)"
er="$(printf '{"session_id":"t3","prompt":"please handle demoword now"}' \
      | EPISODIC_STATE_DIR="$st3" bash "$SETUP/episodic-recall.sh" 2>/dev/null || true)"
printf '%s' "$er" | grep -q 'demo' || fail "episodic-recall did not surface memory/episodic (out=[$er])"

# 5. playbook-guard RESOLVES + FIRES from memory/playbooks: a command matching the
#    fixture's tool_match must inject the fixture playbook body (non-vacuous — proves
#    the guard read <content>/memory/playbooks/INDEX.md, not just "didn't crash").
st4="$(mktemp -d)"
gr="$(printf '{"session_id":"t4","tool_name":"Bash","tool_input":{"command":"run demoword now"}}' \
      | EPISODIC_STATE_DIR="$st4" bash "$SETUP/playbook-guard.sh" 2>/dev/null || true)"
printf '%s' "$gr" | grep -q 'demo' || fail "playbook-guard did not resolve+fire from memory/playbooks (out=[$gr])"

# 6. wiki_index indexes topic AND concept as folders, each with co-located sources
py="$(NP_CONTENT_DIR="$FIX" WIKI_NAV=on python3 - "$REPO" <<'PY'
import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], "dashboard"))
import build
idx = build.wiki_index()
t = {x["topic"]: x for x in idx["topics"]}
c = {x["name"]: x for x in idx["concepts"]}
assert "demo" in t and t["demo"]["synthesis"], "topic synthesis missing"
assert any(s["name"] == "demo-ref" for s in t["demo"]["sources"]), "topic co-located source missing"
assert "idea" in c and c["idea"]["synthesis"], "concept synthesis missing"
assert any(s["name"] == "idea-ref" for s in c["idea"]["sources"]), "concept co-located source missing"
print("WIKI_OK")
PY
)" || fail "wiki_index raised (out=[$py])"
printf '%s' "$py" | grep -q WIKI_OK || fail "wiki_index did not index topic+concept folders with sources (out=[$py])"

# 7. graduation detector reads memory/{strategies,playbooks} and emits valid JSON
gd="$(python3 "$SETUP/np-graduation-detect.py" "$FIX/memory/strategies" "$FIX/memory/playbooks" 2>/dev/null || true)"
printf '%s' "$gd" | jq -e 'has("candidates")' >/dev/null 2>&1 \
  || fail "graduation-detect did not read memory/ (out=[$gd])"

echo "OK example-layout compatibility"
