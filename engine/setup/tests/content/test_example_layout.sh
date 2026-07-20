#!/usr/bin/env bash
# Anti-drift contract: the engine must read EVERY layer the canonical example
# skeleton ships (memory/{episodic,lessons} + wiki/{topics,concepts}/<x>/
# with co-located sources). If a reader stops resolving a canonical-layout layer,
# this goes red. Zero-dep; runs each reader against a committed fixture via
# NP_CONTENT_DIR. Assertions check real fixture CONTENT (not just "no error"), so a
# reader that silently resolves the wrong path fails here.
#
# memory/lessons/ replaces the old memory/{playbooks,strategies} split (merged —
# see docs/superpowers/specs/2026-07-02-lessons-layer-merge-design.md): a single
# demo.md carries BOTH provenances back to back (failure = former playbook,
# success = former strategy), matching how np-migrate-lessons.py folds a topic
# that existed in both old layers into one file. Readers under test: lesson-
# recall (merge of playbook-recall.sh + strategy-recall.sh, now the Python
# module hooks/lesson_recall.py) and lesson-guard (renamed from playbook-
# guard.sh, now the Python module hooks/lesson_guard.py) -- both dispatched
# via engine/nervepack_engine/cli.py.
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
out="$(bash -c 'source "'"$SETUP/np-layer-lib.sh"'"; np_layer_roots lessons')"
[ "$out" = "$FIX/memory/lessons" ] || fail "np_layer_roots lessons -> [$out], want [$FIX/memory/lessons]"

# 2. lesson-recall surfaces BOTH provenances of the fixture's merged demo.md from
#    memory/lessons: the failure-provenance body (former playbook) with its
#    "past failure pattern" framing, and the success-provenance body (former
#    strategy) with its "worked" framing -- one hook, one call, both blocks.
st="$(mktemp -d)"
lr="$(printf '{"session_id":"t1","prompt":"please handle demoword now"}' \
      | EPISODIC_STATE_DIR="$st" python3 "$REPO/engine/nervepack_engine/cli.py" hook lesson-recall 2>/dev/null || true)"
printf '%s' "$lr" | grep -q 'demo' || fail "lesson-recall did not surface memory/lessons (out=[$lr])"
printf '%s' "$lr" | grep -qi 'past failure' || fail "lesson-recall missing failure-provenance framing (out=[$lr])"
printf '%s' "$lr" | grep -qi 'worked' || fail "lesson-recall missing success-provenance framing (out=[$lr])"

# 3. episodic-recall (Python CLI) surfaces the fixture episodic theme from memory/episodic
st3="$(mktemp -d)"
er="$(printf '{"session_id":"t3","prompt":"please handle demoword now"}' \
      | EPISODIC_STATE_DIR="$st3" python3 "$REPO/engine/nervepack_engine/cli.py" hook episodic-recall 2>/dev/null || true)"
printf '%s' "$er" | grep -q 'demo' || fail "episodic-recall did not surface memory/episodic (out=[$er])"

# 4. lesson-guard RESOLVES + FIRES from memory/lessons: a command matching the
#    fixture's tool_match must inject the fixture lesson body (non-vacuous — proves
#    the guard read <content>/memory/lessons/INDEX.md, not just "didn't crash").
st4="$(mktemp -d)"
gr="$(printf '{"session_id":"t4","tool_name":"Bash","tool_input":{"command":"run demoword now"}}' \
      | EPISODIC_STATE_DIR="$st4" python3 "$REPO/engine/nervepack_engine/cli.py" hook lesson-guard 2>/dev/null || true)"
printf '%s' "$gr" | grep -q 'demo' || fail "lesson-guard did not resolve+fire from memory/lessons (out=[$gr])"

# 5. wiki_index indexes topic AND concept as folders, each with co-located sources
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

# 6. graduation detector reads a memory/ dir and emits valid JSON. np-graduation-
#    detect.py is directory-generic (kind is a caller-supplied label, not read
#    from frontmatter) and has not itself been migrated to a lessons-aware dual-
#    provenance scan (tracked separately) -- pointing it at memory/lessons still
#    exercises "the engine can read this merged layer" without depending on the
#    now-removed memory/{strategies,playbooks} dirs.
gd="$(python3 "$SETUP/np-graduation-detect.py" "$FIX/memory/lessons" 2>/dev/null || true)"
printf '%s' "$gd" | jq -e 'has("candidates")' >/dev/null 2>&1 \
  || fail "graduation-detect did not read memory/lessons (out=[$gd])"

echo "OK example-layout compatibility"
