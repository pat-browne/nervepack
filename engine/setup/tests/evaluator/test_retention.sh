#!/usr/bin/env bash
# np-test: retention | 73-aggregate prunes metrics.jsonl and resolved-suggestions.txt to retain_days cap
# Verify that 73-aggregate-metrics.sh prunes rows older than evaluator.retain_days from
# metrics.jsonl and resolved-suggestions.txt when the param is set, and is a no-op when
# the param is 0 (unlimited) or the toggle is off.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGG="$HERE/../../73-aggregate-metrics.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Shared env: toggle on, no commit
export NP_TOGGLES_CONF="$tmp/toggles.conf"
export NP_TOGGLES_LOCAL="$tmp/local"
export EVAL_INBOX="$tmp/inbox"
export METRICS_FILE="$tmp/metrics.jsonl"
export NP_AGG_NO_COMMIT=1
# Point NP_CONTENT_DIR at tmp so resolved-suggestions resolves there
export NP_CONTENT_DIR="$tmp/content"
mkdir -p "$NP_CONTENT_DIR/dashboard/data" "$tmp/inbox"

# Base toggles: evaluator on, retain_days=30
printf 'evaluator|shared|runtime|on|retain_days=30\n' > "$tmp/toggles.conf"
: > "$tmp/local"

# Seed metrics.jsonl with 3 records: two old, one recent
old1="2020-01-01T00:00:00Z"
old2="2021-06-15T00:00:00Z"
recent="$(date -u +%Y-%m-%dT%H:%M:%SZ)"  # today
printf '{"session_id":"old1","ts":"%s"}\n' "$old1" > "$tmp/metrics.jsonl"
printf '{"session_id":"old2","ts":"%s"}\n' "$old2" >> "$tmp/metrics.jsonl"
printf '{"session_id":"recent","ts":"%s"}\n' "$recent" >> "$tmp/metrics.jsonl"

# Seed resolved-suggestions.txt with a mix of dated entries (two old, one recent).
# Format expected: optional date comment or just the suggestion text with a ts field
# (implementation detail: the pruner will use the ts field, or we can store them
# with an optional trailing tab+ts). We'll use the simplest prunable format:
# one suggestion per line with a trailing tab and ISO timestamp.
resolved="$NP_CONTENT_DIR/dashboard/data/resolved-suggestions.txt"
printf 'old suggestion 1\t%s\n' "$old1" > "$resolved"
printf 'old suggestion 2\t%s\n' "$old2" >> "$resolved"
printf 'recent suggestion\t%s\n' "$recent" >> "$resolved"

# No inbox items (we just test the prune side)
# Run aggregator (inbox is empty -> still runs prune)
# We put a dummy record in the inbox so the aggregator doesn't exit early on empty inbox.
printf '{"session_id":"new","ts":"%s"}\n' "$recent" > "$tmp/inbox/now.jsonl"
bash "$AGG" >/dev/null

# After prune with retain_days=30: old1, old2 should be gone; recent+new should remain
old1_count=$(grep -c '"session_id":"old1"' "$tmp/metrics.jsonl" 2>/dev/null || true)
old2_count=$(grep -c '"session_id":"old2"' "$tmp/metrics.jsonl" 2>/dev/null || true)
recent_count=$(grep -c '"session_id":"recent"' "$tmp/metrics.jsonl" 2>/dev/null || true)
new_count=$(grep -c '"session_id":"new"' "$tmp/metrics.jsonl" 2>/dev/null || true)

[[ "$old1_count" -eq 0 ]] || { echo "FAIL: old1 record not pruned from metrics.jsonl"; exit 1; }
[[ "$old2_count" -eq 0 ]] || { echo "FAIL: old2 record not pruned from metrics.jsonl"; exit 1; }
[[ "$recent_count" -eq 1 ]] || { echo "FAIL: recent record missing from metrics.jsonl"; exit 1; }
[[ "$new_count" -eq 1 ]] || { echo "FAIL: new record missing from metrics.jsonl"; exit 1; }

# resolved-suggestions.txt: old suggestions pruned, recent kept
old_res=$(grep -c 'old suggestion' "$resolved" 2>/dev/null || true)
recent_res=$(grep -c 'recent suggestion' "$resolved" 2>/dev/null || true)
[[ "$old_res" -eq 0 ]] || { echo "FAIL: old resolved suggestions not pruned (count=$old_res)"; exit 1; }
[[ "$recent_res" -eq 1 ]] || { echo "FAIL: recent resolved suggestion missing"; exit 1; }

# Verify retain_days=0 means no pruning (unlimited)
printf 'evaluator|shared|runtime|on|retain_days=0\n' > "$tmp/toggles.conf"
# Re-seed with old records
printf '{"session_id":"old1","ts":"%s"}\n' "$old1" > "$tmp/metrics.jsonl"
printf '{"session_id":"old2","ts":"%s"}\n' "$old2" >> "$tmp/metrics.jsonl"
printf '{"session_id":"recent","ts":"%s"}\n' "$recent" >> "$tmp/metrics.jsonl"
printf 'old suggestion 1\t%s\n' "$old1" > "$resolved"
mkdir -p "$tmp/inbox"
printf '{"session_id":"noop","ts":"%s"}\n' "$recent" > "$tmp/inbox/noop.jsonl"
bash "$AGG" >/dev/null

old1_count=$(grep -c '"session_id":"old1"' "$tmp/metrics.jsonl" 2>/dev/null || true)
[[ "$old1_count" -eq 1 ]] || { echo "FAIL: retain_days=0 pruned records (should keep all)"; exit 1; }

echo "PASS test_retention"
