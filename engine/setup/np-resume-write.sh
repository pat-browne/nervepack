#!/usr/bin/env bash
# np-resume-write.sh — deterministic resume-pointer writer (NO LLM calls).
#
# Usage:
#   np-resume-write.sh --session <id> --transcript <path> --cwd <dir> [--throttle]
#   np-resume-write.sh --active [--throttle]
#
# Flags (not stdin) so SessionStart/cron callers don't have to fake a hook payload;
# UserPromptSubmit-style callers just forward the fields they already have.
#
# --active: for the opt-in interval cron (70-install-memory-cron.sh), which has no
# stdin/hook payload to source --session/--transcript/--cwd from. Discovers the
# current session as the NEWEST ${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}/*/*.jsonl
# by mtime that is NOT an `agent-*` subagent transcript, derives session_id from its
# basename and cwd from the transcript's own embedded `"cwd":"..."`, then proceeds
# exactly as the explicit-flags path. Composes with --throttle. No candidate found ->
# exit 0 silently (nothing to record yet).
#
# Writes ${NP_RESUME_POINTER:-$HOME/.cache/nervepack/resume-pointer.json} atomically
# (tmp file + `mv`):
#   {schema_version:1, session_id, ts:<epoch>, cwd, git_branch, git_head,
#    git_dirty:(true|false), transcript_path, last_user_instruction, sdd_ledger,
#    sdd_plan}
#
#   - git fields come from `git -C "$cwd"`, and ONLY if $cwd is a git work-tree;
#     otherwise every git_* field is empty/false. git_head is the short SHA.
#   - last_user_instruction is `np-transcript-extract.py --last-user` (Task 1) —
#     empty on any failure.
#   - sdd_ledger is <repo-root>/.superpowers/sdd/progress.md if it exists; sdd_plan
#     is the value after "Plan:" on that ledger's Plan: line, if present.
#
# --throttle: honor `np_param resume.interval 300` via
# ${NP_RESUME_STAMP:-$HOME/.cache/nervepack/last-resume-write} (same epoch-diff
# pattern as 40-sync-nervepack.sh) — within the interval, exit 0 without writing.
# Without --throttle, always write. The stamp is (re)written after every
# successful pointer write, throttled or not, so a later --throttle call always
# measures time-since-last-actual-write.
#
# Fail-open: every failure path exits 0; bail() optionally logs one line to
# ${NP_RESUME_LOG:-$HOME/.cache/nervepack/resume.log}. Never breaks a session.
set -uo pipefail
[[ -n "${NERVEPACK_AGENT:-}" ]] && exit 0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_npl="$HERE/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled resume || exit 0; }

LOG="${NP_RESUME_LOG:-$HOME/.cache/nervepack/resume.log}"
bail() { mkdir -p "$(dirname "$LOG")" 2>/dev/null && printf '%s resume: %s\n' "$(date -u +%FT%TZ)" "$1" >> "$LOG" 2>/dev/null; exit 0; }

# Portable epoch mtime (BSD has no `stat -c`/`find -printf`): try GNU then BSD.
np_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

command -v jq >/dev/null 2>&1 || bail "jq not found"

SESSION="" TRANSCRIPT="" CWD="" THROTTLE=0 ACTIVE=0
# Guard each value-taking flag: `shift 2` with only one positional left is a no-op
# (bash leaves $1 unchanged; with no `set -e` the non-zero shift is swallowed), so
# an unguarded parser loops forever on a trailing value-less flag (e.g. a caller
# collapsing `--cwd "$X"` into a lone `--cwd` when $X is empty). Bail fail-open.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)    [[ $# -ge 2 ]] || bail "missing value for --session";    SESSION="$2";    shift 2;;
    --transcript) [[ $# -ge 2 ]] || bail "missing value for --transcript"; TRANSCRIPT="$2"; shift 2;;
    --cwd)        [[ $# -ge 2 ]] || bail "missing value for --cwd";        CWD="$2";        shift 2;;
    --throttle) THROTTLE=1; shift;;
    --active)   ACTIVE=1; shift;;
    *) shift;;
  esac
done

# --active: discover the current/most-recent session transcript instead of relying
# on --session/--transcript/--cwd (the cron caller has neither stdin nor a hook
# payload to source them from). Newest-first by mtime, skipping agent-* subagent
# transcripts — the first survivor is the active session.
if [[ "$ACTIVE" == 1 ]]; then
  PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
  active_tpath=""
  if [[ -d "$PROJECTS_DIR" ]]; then
    while IFS= read -r tpath; do
      [[ -n "$tpath" && -f "$tpath" ]] || continue
      sid="$(basename "$tpath" .jsonl)"
      [[ -n "$sid" ]] || continue
      [[ "$sid" == agent-* ]] && continue
      active_tpath="$tpath"
      break   # newest-first -> first non-agent survivor is the active session
    done < <(find "$PROJECTS_DIR" -name '*.jsonl' -type f 2>/dev/null \
               | while IFS= read -r p; do printf '%s %s\n' "$(np_mtime "$p" 2>/dev/null || echo 0)" "$p"; done \
               | sort -rn | cut -d' ' -f2-)
  fi
  [[ -n "$active_tpath" ]] || exit 0   # no candidate -> nothing to record, silent
  SESSION="$(basename "$active_tpath" .jsonl)"
  TRANSCRIPT="$active_tpath"
  CWD="$(grep -m1 -oE '"cwd":"[^"]*"' "$active_tpath" 2>/dev/null | head -1 | sed -E 's/^"cwd":"//; s/"$//')"
fi

[[ -n "$CWD" ]] || bail "missing required --cwd"

POINTER="${NP_RESUME_POINTER:-$HOME/.cache/nervepack/resume-pointer.json}"
STAMP="${NP_RESUME_STAMP:-$HOME/.cache/nervepack/last-resume-write}"

if [[ "$THROTTLE" == 1 && -f "$STAMP" ]]; then
  _interval="$(np_param resume.interval 300 2>/dev/null || echo 300)"
  [[ "$_interval" =~ ^[0-9]+$ ]] || _interval=300
  _age=$(( $(date +%s) - $(cat "$STAMP" 2>/dev/null || echo 0) ))
  [[ "$_age" -lt "$_interval" ]] && exit 0
fi

mkdir -p "$(dirname "$POINTER")" 2>/dev/null || bail "mkdir failed for $(dirname "$POINTER")"

# --- git fields: only if $CWD is a git work-tree; else empty/false ---
git_branch="" git_head="" git_dirty=false repo_root=""
if git -C "$CWD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git_branch="$(git -C "$CWD" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  git_head="$(git -C "$CWD" rev-parse --short HEAD 2>/dev/null || true)"
  [[ -n "$(git -C "$CWD" status --porcelain 2>/dev/null)" ]] && git_dirty=true
  repo_root="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || true)"
fi

# --- last user instruction (Task 1's extractor); empty on any failure ---
last_user=""
if [[ -n "$TRANSCRIPT" && -x "$HERE/np-transcript-extract.py" ]]; then
  last_user="$("$HERE/np-transcript-extract.py" --last-user "$TRANSCRIPT" 2>/dev/null)" || last_user=""
fi

# --- sdd ledger + plan ---
sdd_ledger="" sdd_plan=""
if [[ -n "$repo_root" && -f "$repo_root/.superpowers/sdd/progress.md" ]]; then
  sdd_ledger="$repo_root/.superpowers/sdd/progress.md"
  sdd_plan="$(grep -m1 '^Plan:' "$sdd_ledger" 2>/dev/null | sed -E 's/^Plan:[[:space:]]*//')"
fi

ts="$(date +%s)"

tmp="$(mktemp "${POINTER}.tmp.XXXXXX" 2>/dev/null)" || bail "mktemp failed"
jq -n \
  --argjson schema_version 1 \
  --arg session_id "$SESSION" \
  --argjson ts "$ts" \
  --arg cwd "$CWD" \
  --arg git_branch "$git_branch" \
  --arg git_head "$git_head" \
  --argjson git_dirty "$git_dirty" \
  --arg transcript_path "$TRANSCRIPT" \
  --arg last_user_instruction "$last_user" \
  --arg sdd_ledger "$sdd_ledger" \
  --arg sdd_plan "$sdd_plan" \
  '{schema_version:$schema_version, session_id:$session_id, ts:$ts, cwd:$cwd,
    git_branch:$git_branch, git_head:$git_head, git_dirty:$git_dirty,
    transcript_path:$transcript_path, last_user_instruction:$last_user_instruction,
    sdd_ledger:$sdd_ledger, sdd_plan:$sdd_plan}' \
  > "$tmp" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; bail "jq build failed"; }

mv "$tmp" "$POINTER" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; bail "mv failed"; }

mkdir -p "$(dirname "$STAMP")" 2>/dev/null && date +%s > "$STAMP" 2>/dev/null

exit 0
