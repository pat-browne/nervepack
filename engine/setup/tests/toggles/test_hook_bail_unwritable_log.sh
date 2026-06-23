#!/usr/bin/env bash
# np-test: hook-lib-bail | failure
# Invariant 1 (fail-open): a nervepack lifecycle hook must NEVER disrupt the
# session, even when its own breadcrumb log is unwritable. The shared bail()
# pattern is `mkdir -p <logdir> 2>/dev/null && printf ... >> <log> 2>/dev/null;
# exit 0` — the `2>/dev/null` swallows the I/O failure and `exit 0` always runs.
# This drives episodic-capture.sh (a representative bail() owner) down a real bail
# branch with EPISODIC_CAPTURE_LOG pointed at an UNWRITABLE path (its parent is a
# regular file, so mkdir -p fails) and asserts: exit 0, no stray output, and the
# log was genuinely never created. Guards against a regression that drops the
# `2>/dev/null`/`exit 0` and lets a logging failure crash the hook.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAP="$HERE/../../episodic-capture.sh"
command -v jq >/dev/null || { echo "PASS test_hook_bail_unwritable_log (skipped — jq missing)"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Make the log's parent a FILE so `mkdir -p "$(dirname LOG)"` cannot succeed.
printf 'i am a file, not a dir\n' > "$tmp/blocker"
LOG="$tmp/blocker/episodic-capture.log"   # parent is a file -> unwritable

# A real transcript + a seen-file whose fingerprint matches its byte size forces
# the dedup bail (`skip: transcript unchanged`) — a genuine bail() call, not an
# earlier plain `exit 0` guard.
transcript="$tmp/transcript.jsonl"
printf '{"type":"user","message":{"role":"user","content":"hi"}}\n' > "$transcript"
fp="$(wc -c < "$transcript" | tr -d '[:space:]')"   # match episodic-capture.sh's fingerprint (portable; BSD has no `stat -c`)
seen_dir="$tmp/seen"; mkdir -p "$seen_dir"
sid="sess1"
printf '%s' "$fp" > "$seen_dir/$sid"

payload="$(jq -n --arg t "$transcript" --arg c "$tmp" --arg s "$sid" \
  '{transcript_path:$t, cwd:$c, session_id:$s}')"

rc=0; out="$(printf '%s' "$payload" | \
  EPISODIC_CAPTURE_LOG="$LOG" \
  EPISODIC_INBOX="$tmp/inbox" \
  EPISODIC_SEEN_DIR="$seen_dir" \
  NP_LLM_BACKEND=local \
  bash "$CAP" session-end 2>&1)" || rc=$?

[[ "$rc" == 0 ]] || { echo "FAIL: bail with unwritable log exited $rc (want 0): $out"; exit 1; }
[[ -z "$out" ]] || { echo "FAIL: hook emitted output on a fail-open bail: $out"; exit 1; }
# The unwritable log must NOT have been created (parent is a file) — proves the
# write really failed yet the hook still exited 0.
[[ ! -e "$LOG" ]] || { echo "FAIL: log path unexpectedly created at $LOG"; exit 1; }
[[ -f "$tmp/blocker" ]] || { echo "FAIL: the blocker file was clobbered"; exit 1; }
echo "PASS test_hook_bail_unwritable_log"
