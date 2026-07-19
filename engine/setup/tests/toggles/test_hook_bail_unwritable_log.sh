#!/usr/bin/env bash
# np-test: hook-lib-bail | failure
# Invariant 1 (fail-open): every nervepack lifecycle hook/cron must NEVER
# disrupt the caller, even when its own breadcrumb log is unwritable. The
# shared `bail()` idiom is `mkdir -p <logdir> ... && printf/echo ... >> <log>
# ...; exit 0` so that a logging I/O failure degrades instead of crashing.
#
# Originally this drove episodic-capture.sh (retired to Python in this same
# migration phase) down a real bail branch. Retargeted at 77-run-compact.sh —
# a still-bash weekly cron (not scheduled for retirement until Task 3) whose
# `bail()` uses the exact same env-var-overridable LOG path + "make LOG's
# parent a file so mkdir -p can't create it" shape. (76-run-refine.sh was a
# byte-for-byte twin of this bail() shape but is now retired to Python.)
#
# One real difference from episodic-capture.sh's bail(): 77-run-compact.sh's
# `mkdir -p "$(dirname "$LOG")"` and the `bail()` log-append are NOT
# `2>/dev/null`-suppressed, so an unwritable log dir does print a couple of
# diagnostic lines to STDERR (confirmed by hand: "mkdir: ... Not a directory"
# / "...: No such file or directory"). That stderr noise is tolerated here —
# it's not part of any contract anything reads. What still matters, and is
# asserted below, is the invariant itself: exit 0 (never crashes, `set -uo
# pipefail` has no `-e` so the failed mkdir/append don't abort the script),
# clean STDOUT (nothing that could look like real hook output), and the log
# file genuinely never created (the write really failed, this isn't a no-op
# success).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$HERE/../../77-run-compact.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
: > "$tmp/toggles.conf"
echo "maintain.compact=on" > "$tmp/local"   # make the toggle explicit/hermetic

# Make the log's parent a FILE so `mkdir -p "$(dirname "$LOG")"` cannot succeed.
printf 'i am a file, not a dir\n' > "$tmp/blocker"
LOG="$tmp/blocker/compact.log"   # parent is a file -> unwritable

# Force a real bail() call deterministically: point CLAUDE_BIN at a path that
# doesn't exist so the backend pre-flight check bails with "claude CLI not
# found" before any agent/network call is attempted.
rc=0
stdout="$(COMPACT_LOG="$LOG" CLAUDE_BIN="$tmp/no-such-claude" NP_LLM_BACKEND=claude \
  bash "$W" 2>/dev/null)" || rc=$?

[[ "$rc" == 0 ]] || { echo "FAIL: bail with unwritable log exited $rc (want 0)"; exit 1; }
[[ -z "$stdout" ]] || { echo "FAIL: script emitted stray stdout on a fail-open bail: $stdout"; exit 1; }
# The unwritable log must NOT have been created (parent is a file) — proves the
# write really failed yet the script still exited 0.
[[ ! -e "$LOG" ]] || { echo "FAIL: log path unexpectedly created at $LOG"; exit 1; }
[[ -f "$tmp/blocker" ]] || { echo "FAIL: the blocker file was clobbered"; exit 1; }
echo "PASS test_hook_bail_unwritable_log"
