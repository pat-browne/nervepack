#!/usr/bin/env bash
# SessionStart resume-pointer writer — the reliable-trigger backstop for the
# "resume pointer" feature.
#
# Task 2's writer (np-resume-write.sh) fires on a throttle from the live session
# and can miss the FINAL tick before that session ends, leaving a stale pointer.
# SessionStart is the reliable trigger (ARCHITECTURE invariant 12: SessionStart is
# awaited, SessionEnd is not — see np-backcapture-sweep.sh's header for the same
# reasoning), so on every new session this script reconstructs the pointer for the
# most-recent COMPLETED PRIOR session from disk, independent of whatever the live
# writer managed to capture.
#
# Reads the SessionStart stdin payload {session_id, cwd}. Enumerates
# ${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}/*/*.jsonl newest-first by mtime
# (idioms straight from np-backcapture-sweep.sh: np_mtime, the same discriminators).
# Skips: the current (active) session, agent-* subagent transcripts, and anything
# not yet settled (mtime younger than MIN_AGE_SEC == 120s, i.e. still being
# written). Since the list is newest-first, the first survivor IS the most-recent
# completed prior session — take it and stop scanning.
#
# That candidate's cwd is read from its OWN transcript (embedded `"cwd":"..."`),
# falling back to the current payload's cwd, then $HOME, if absent. Hands off to
# np-resume-write.sh (Task 2) WITHOUT --throttle — SessionStart always forces a
# fresh write. No settled prior session found -> exit 0 silently (nothing to
# record yet).
#
# Fail-open throughout: every path exits 0; bail() optionally logs one line to
# ${NP_RESUME_LOG:-$HOME/.cache/nervepack/resume.log}. No unbounded loops.
set -uo pipefail
# Re-entry guard: mirrors np-backcapture-sweep.sh / np-resume-write.sh — if we're
# already inside a `claude -p` invocation, do nothing.
[[ -n "${NERVEPACK_AGENT:-}" ]] && exit 0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_npl="$HERE/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled resume || exit 0; }

LOG="${NP_RESUME_LOG:-$HOME/.cache/nervepack/resume.log}"
bail() { mkdir -p "$(dirname "$LOG")" 2>/dev/null && printf '%s resume-sessionstart: %s\n' "$(date -u +%FT%TZ)" "$1" >> "$LOG" 2>/dev/null; exit 0; }

command -v jq >/dev/null 2>&1 || bail "jq not found"

# Portable epoch mtime (BSD has no `stat -c`/`find -printf`): try GNU then BSD.
np_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

payload="$(cat 2>/dev/null || true)"
cur_sid="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null || true)"
cur_cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)"

PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
[[ -d "$PROJECTS_DIR" ]] || exit 0

MIN_AGE_SEC="${NP_RESUME_MIN_AGE_SEC:-120}"   # skip transcripts touched recently (likely still active)
now="$(date +%s)"

prior_sid="" prior_tpath=""
while IFS= read -r tpath; do
  [[ -n "$tpath" && -f "$tpath" ]] || continue
  sid="$(basename "$tpath" .jsonl)"
  [[ -n "$sid" ]] || continue
  [[ "$sid" == agent-* ]] && continue                       # subagent transcript, not a real session
  [[ "$sid" == "$cur_sid" ]] && continue                    # the active session
  mt="$(np_mtime "$tpath")"; mt="${mt:-$now}"
  (( now - mt < MIN_AGE_SEC )) && continue                  # unsettled / not yet completed
  prior_sid="$sid"; prior_tpath="$tpath"
  break   # newest-first -> first survivor is the most-recent completed prior session
done < <(find "$PROJECTS_DIR" -name '*.jsonl' -type f 2>/dev/null \
           | while IFS= read -r p; do printf '%s %s\n' "$(np_mtime "$p")" "$p"; done \
           | sort -rn | cut -d' ' -f2-)

[[ -n "$prior_sid" ]] || exit 0   # no completed prior session -> nothing to record

prior_cwd="$(grep -m1 -oE '"cwd":"[^"]*"' "$prior_tpath" 2>/dev/null | head -1 | sed -E 's/^"cwd":"//; s/"$//')"
[[ -n "$prior_cwd" ]] || prior_cwd="${cur_cwd:-$HOME}"

[[ -x "$HERE/np-resume-write.sh" ]] || bail "np-resume-write.sh missing/not executable"

# No --throttle: SessionStart always forces a fresh write of the reconstructed pointer.
# Note: this non-throttled write also updates the SHARED throttle stamp
# (NP_RESUME_STAMP), so the current session's first live UserPromptSubmit write
# (np-resume-recall.sh, which IS throttled) may be deferred up to `resume.interval`.
# Crash-recovery is unaffected: the next SessionStart reconstructs directly from the
# settled transcript on disk, regardless of the stamp.
"$HERE/np-resume-write.sh" --session "$prior_sid" --transcript "$prior_tpath" --cwd "$prior_cwd" \
  || bail "np-resume-write.sh failed for $prior_sid"

exit 0
