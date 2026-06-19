#!/usr/bin/env bash
# SessionStart back-capture sweep — the reliable backstop for session capture.
#
# Claude Code does NOT reliably run slow SessionEnd `claude -p` hooks to
# completion: it exits the process without awaiting them, and `/exit` doesn't fire
# SessionEnd at all (GH anthropics/claude-code #35892, #41577). So episodic-capture
# and np-evaluator — each a ~15-30s headless call — get killed mid-flight, and
# nearly every session is lost (no inbox note, no metrics record). See
# [[np-kb-claude-headless-scripting]].
#
# This sweep runs at SessionStart (which IS awaited) and is registered with a
# trailing `&` so it never delays session start; the parent session stays alive
# long enough for the model calls to finish. It scans completed prior-session
# transcripts, and for any with no record yet runs the EXISTING capture + evaluator
# against the saved transcript (reuse, not reimplement). Idempotent (per-sid claim
# marker), bounded (recent days, capped count), fail-open (never disrupts startup).
set -uo pipefail
# Re-entry guard: the capture/evaluator we invoke call `claude -p` (which sets
# NERVEPACK_AGENT); if we're already inside one, do nothing.
[[ -n "${NERVEPACK_AGENT:-}" ]] && exit 0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-toggle-lib.sh"
source "$HERE/np-content-lib.sh"
np_enabled memory.backcapture || exit 0

command -v jq >/dev/null || exit 0
command -v python3 >/dev/null || exit 0

LOG="${BACKCAPTURE_LOG:-$HOME/.cache/nervepack/backcapture.log}"
log() { mkdir -p "$(dirname "$LOG")" 2>/dev/null && printf '%s backcapture: %s\n' "$(date -u +%FT%TZ)" "$1" >> "$LOG" 2>/dev/null; }

# Portable epoch mtime (BSD has no `stat -c`/`find -printf`): try GNU then BSD.
np_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
[[ -d "$PROJECTS_DIR" ]] || exit 0
SEEN_DIR="${BACKCAPTURE_SEEN_DIR:-$HOME/.cache/nervepack/backcapture-seen}"
mkdir -p "$SEEN_DIR" 2>/dev/null || exit 0
METRICS="${BACKCAPTURE_METRICS:-$(np_content_dir)/dashboard/data/metrics.jsonl}"
CAPTURE="$HERE/episodic-capture.sh"
EVAL="$HERE/np-evaluator.sh"

DAYS="$(np_param memory.backcapture_days 2)"
MAX="$(np_param memory.backcapture_max 5)"
MIN_AGE_SEC="${BACKCAPTURE_MIN_AGE_SEC:-120}"   # skip transcripts touched recently (likely an active session)

# Best-effort: don't capture the in-progress session (the MIN_AGE guard also covers
# this, since an active transcript is being written and is therefore recent).
payload="$(cat 2>/dev/null || true)"
cur_sid="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null || true)"

now="$(date +%s)"
processed=0

# Candidate transcripts modified within DAYS days, newest first (one .jsonl per
# session; filename stem == session_id).
while IFS= read -r tpath; do
  [[ -n "$tpath" && -f "$tpath" ]] || continue
  (( processed >= MAX )) && break
  sid="$(basename "$tpath" .jsonl)"
  [[ -n "$sid" ]] || continue
  [[ "$sid" == agent-* ]] && continue                      # subagent transcript, not a real session
  [[ "$sid" == "$cur_sid" ]] && continue
  mt="$(np_mtime "$tpath")"; mt="${mt:-$now}"
  (( now - mt < MIN_AGE_SEC )) && continue                 # unsettled / active
  [[ -e "$SEEN_DIR/$sid" ]] && continue                    # already handled
  # Already has a committed metrics record -> nothing to do; mark seen so we stop
  # re-checking it on every session start.
  if [[ -f "$METRICS" ]] && grep -q "$sid" "$METRICS" 2>/dev/null; then
    : > "$SEEN_DIR/$sid" 2>/dev/null || true
    continue
  fi
  # Claim atomically (race-safe against a concurrent sweep): noclobber `>` fails if
  # the marker already exists. Marking before processing also means a failed
  # back-capture is not retried in a storm — acceptable, the loss we fix is systematic.
  ( set -C; : > "$SEEN_DIR/$sid" ) 2>/dev/null || continue
  cwd="$(grep -m1 -oE '"cwd":"[^"]*"' "$tpath" 2>/dev/null | head -1 | sed -E 's/^"cwd":"//; s/"$//')"
  [[ -n "$cwd" ]] || cwd="$HOME"
  bp="$(jq -nc --arg sid "$sid" --arg tp "$tpath" --arg cwd "$cwd" \
    '{session_id:$sid, transcript_path:$tp, cwd:$cwd}' 2>/dev/null)" || continue
  # Reuse the existing pipeline. Both self-guard their internal `claude -p`
  # (NERVEPACK_AGENT, set by np-llm.sh) and capture self-dedups (capture-seen).
  printf '%s' "$bp" | "$CAPTURE" session-end >/dev/null 2>&1 || true
  printf '%s' "$bp" | "$EVAL" >/dev/null 2>&1 || true
  processed=$((processed + 1))
  log "back-captured $sid (project $(basename "$cwd"))"
done < <(find "$PROJECTS_DIR" -name '*.jsonl' -type f -mtime "-$DAYS" 2>/dev/null \
           | while IFS= read -r p; do printf '%s %s\n' "$(np_mtime "$p")" "$p"; done \
           | sort -rn | cut -d' ' -f2-)

(( processed > 0 )) && log "sweep done: $processed session(s)"
exit 0
