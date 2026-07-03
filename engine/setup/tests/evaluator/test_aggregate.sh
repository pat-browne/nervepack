#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGG="$HERE/../../73-aggregate-metrics.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/dashboard/data"
# Isolate the build OUTPUT too: 73-aggregate writes metrics.js to
# $NP_CONTENT_DIR/dashboard/data/metrics.js. Without pinning NP_CONTENT_DIR here, it
# resolves via _content_dir() to the engine root — whose dashboard/data is a SYMLINK
# into the live content overlay — so the test would clobber the user's real dashboard
# data (empty WIKI/LEARNED, because the engine root has no wiki/lessons).
export NP_CONTENT_DIR="$tmp" NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
  EVAL_INBOX="$tmp/inbox" METRICS_FILE="$tmp/metrics.jsonl" NP_AGG_NO_COMMIT=1
printf 'evaluator|shared|runtime|on|\n' > "$tmp/toggles.conf"
mkdir -p "$tmp/inbox"; printf '{"session_id":"a","contribution_score":50}\n' > "$tmp/inbox/2026-06-03.jsonl"
printf '{"session_id":"b","contribution_score":80}\n' >> "$tmp/inbox/2026-06-03.jsonl"
: > "$tmp/metrics.jsonl"
bash "$AGG" >/dev/null
[[ "$(wc -l < "$tmp/metrics.jsonl" | tr -d '[:space:]')" == "2" ]] || { echo "FAIL: metrics not appended"; exit 1; }
[[ -z "$(ls "$tmp/inbox" 2>/dev/null)" ]] || { echo "FAIL: inbox not cleared"; exit 1; }
# toggle off -> no-op (re-seed)
echo "evaluator.aggregate=off" > "$tmp/local"; printf '{"session_id":"c"}\n' > "$tmp/inbox/x.jsonl"
bash "$AGG" >/dev/null
[[ "$(wc -l < "$tmp/metrics.jsonl" | tr -d '[:space:]')" == "2" ]] || { echo "FAIL: appended while off"; exit 1; }

# NP_LESSONS_DIR must point at memory/lessons. Seed lessons tagged by provenance
# and verify LEARNED counts (failure -> playbooks, success -> strategies) in metrics.js.
mkdir -p "$tmp/memory/lessons"
printf -- '---\nprovenance: failure\n---\nx\n' > "$tmp/memory/lessons/pb1.md"
printf -- '---\nprovenance: success\n---\nx\n' > "$tmp/memory/lessons/st1.md"
: > "$tmp/local"  # re-enable toggles (clear local overrides)
printf '{"session_id":"d","contribution_score":10}\n' > "$tmp/inbox/re-enable.jsonl"
bash "$AGG" >/dev/null
LEARNED_JS="$tmp/dashboard/data/metrics.js"
if [[ ! -f "$LEARNED_JS" ]]; then
  echo "FAIL: metrics.js not written by dashboard build"; exit 1
fi
grep -qE '"playbooks":\s*1' "$LEARNED_JS" || { echo "FAIL: failure lesson not counted in playbooks"; exit 1; }
grep -qE '"strategies":\s*1' "$LEARNED_JS" || { echo "FAIL: success lesson not counted in strategies"; exit 1; }

echo "PASS test_aggregate"
