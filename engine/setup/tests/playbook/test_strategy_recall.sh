#!/usr/bin/env bash
# strategy-recall.sh: on a session's first prompts, inject strategies whose
# topic_triggers match the prompt, with ADVISORY framing + a relevance-gate line.
# Keyword-only, fail-open. (Mirror of playbook-recall, advisory not enforced.)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
RECALL="$SETUP/strategy-recall.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
sdir="$tmp/strategies"; mkdir -p "$sdir"
cat > "$sdir/INDEX.md" <<'IDX'
# strategies — index
| topic | topic_triggers | seen |
|---|---|---:|
| [mirror-the-pipeline](mirror-the-pipeline.md) | memory, layer, recall | 2 |
IDX
cat > "$sdir/mirror-the-pipeline.md" <<'STRAT'
---
name: mirror-the-pipeline
kind: strategy
seen: 2
topic_triggers: [memory, layer, recall]
---
**Title:** Mirror the proven capture pipeline
**When:** adding a new memory/learning layer
**Do:** reuse capture->inbox->maintain->recall instead of new plumbing.
STRAT

run() { EPISODIC_STRATEGY_DIR="$sdir" EPISODIC_STATE_DIR="$tmp/state" bash "$RECALL"; }

# Matching prompt -> strategy injected, with the relevance-gate framing.
out="$(printf '%s' '{"session_id":"s1","prompt":"add a new memory layer to nervepack"}' | run)"
ctx="$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
[[ -n "$ctx" ]] || { echo "FAIL: no context injected for matching prompt: $out"; exit 1; }
printf '%s' "$ctx" | grep -qi 'Mirror the proven capture pipeline' || { echo "FAIL: strategy body not injected: $ctx"; exit 1; }
printf '%s' "$ctx" | grep -qiE 'consider whether|applies' || { echo "FAIL: missing relevance-gate framing: $ctx"; exit 1; }

# Non-matching prompt -> no injection (empty output / no context).
out2="$(printf '%s' '{"session_id":"s2","prompt":"unrelated topic about taxes"}' | run || true)"
ctx2="$(printf '%s' "$out2" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || true)"
[[ -z "$ctx2" ]] || { echo "FAIL: injected for non-matching prompt: $ctx2"; exit 1; }

echo "PASS test_strategy_recall"
