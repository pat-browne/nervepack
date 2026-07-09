#!/usr/bin/env bash
# UserPromptSubmit hook: resume-pointer surfacer + live throttled writer (NO LLM).
#
# ORDER MATTERS:
#   1. SURFACE FIRST — read the pointer left by a PRIOR session. If it describes
#      a DIFFERENT, still-fresh session, emit ONE additionalContext offer naming
#      the prior branch@head (dirty?), the sdd ledger/plan (if any), and the last
#      user instruction. At most once per (current) session — a marker file
#      suppresses re-offering on later prompts of the same session.
#   2. THEN WRITE — invoke np-resume-write.sh --throttle for the CURRENT session,
#      so this session's own pointer is (re)established. Because the write sets
#      session_id==current, subsequent prompts in this same session see a
#      same-session pointer and correctly stay silent. Surfacing therefore MUST
#      happen before the write, else it would always compare against itself.
#
# Fail-open throughout: any parse/read failure just skips surfacing (never
# breaks the prompt); bail() optionally logs one line.
set -uo pipefail
[[ -n "${NERVEPACK_AGENT:-}" ]] && exit 0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_npl="$HERE/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled resume || exit 0; }

LOG="${NP_RESUME_LOG:-$HOME/.cache/nervepack/resume.log}"
bail() { mkdir -p "$(dirname "$LOG")" 2>/dev/null && printf '%s resume-recall: %s\n' "$(date -u +%FT%TZ)" "$1" >> "$LOG" 2>/dev/null; exit 0; }

command -v jq >/dev/null 2>&1 || exit 0

payload="$(cat)"
sid="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)" || sid=""
cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)" || cwd=""
transcript_path="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null)" || transcript_path=""
[[ -n "$sid" ]] || bail "no session_id in payload"

# --- 1. SURFACE FIRST ---------------------------------------------------
STATE_DIR="${NP_RESUME_STATE_DIR:-$HOME/.cache/nervepack/resume-recall-state}"
marker="$STATE_DIR/surfaced_${sid//\//_}"

if [[ ! -f "$marker" ]]; then
  POINTER="${NP_RESUME_POINTER:-$HOME/.cache/nervepack/resume-pointer.json}"
  if [[ -f "$POINTER" ]]; then
    ptr_json="$(cat "$POINTER" 2>/dev/null)"
    if [[ -n "$ptr_json" ]] && printf '%s' "$ptr_json" | jq -e . >/dev/null 2>&1; then
      p_sid="$(printf '%s' "$ptr_json" | jq -r '.session_id // empty' 2>/dev/null)"
      p_ts="$(printf '%s' "$ptr_json" | jq -r '.ts // empty' 2>/dev/null)"
      if [[ -n "$p_sid" && "$p_sid" != "$sid" && "$p_ts" =~ ^[0-9]+$ ]]; then
        now="$(date +%s)"
        max_age="$(np_param resume.max_age 86400 2>/dev/null || echo 86400)"
        [[ "$max_age" =~ ^[0-9]+$ ]] || max_age=86400
        age=$(( now - p_ts ))
        if [[ "$age" -ge 0 && "$age" -lt "$max_age" ]]; then
          p_branch="$(printf '%s' "$ptr_json" | jq -r '.git_branch // empty' 2>/dev/null)"
          p_head="$(printf '%s' "$ptr_json" | jq -r '.git_head // empty' 2>/dev/null)"
          p_dirty="$(printf '%s' "$ptr_json" | jq -r '.git_dirty // false' 2>/dev/null)"
          p_ledger="$(printf '%s' "$ptr_json" | jq -r '.sdd_ledger // empty' 2>/dev/null)"
          p_plan="$(printf '%s' "$ptr_json" | jq -r '.sdd_plan // empty' 2>/dev/null)"
          p_last="$(printf '%s' "$ptr_json" | jq -r '.last_user_instruction // empty' 2>/dev/null)"

          # "~Nm ago" / "~Nh ago", deterministic from age
          if [[ "$age" -lt 3600 ]]; then
            n=$(( age / 60 )); [[ "$n" -lt 1 ]] && n=1
            ago="~${n}m ago"
          else
            n=$(( age / 3600 ))
            ago="~${n}h ago"
          fi

          dirty_note=""
          [[ "$p_dirty" == "true" ]] && dirty_note=" (dirty)"

          where="${p_branch:-unknown branch}@${p_head:-unknown}${dirty_note}"

          msg="A prior nervepack session (${ago}) was working in ${where}"
          [[ -n "$p_last" ]] && msg+=" — ${p_last}"
          msg+=". Resume from"
          parts=()
          [[ -n "$p_ledger" ]] && parts+=("the SDD ledger (${p_ledger})")
          [[ -n "$p_plan" ]] && parts+=("plan ${p_plan}")
          parts+=("the branch")
          if [[ "${#parts[@]}" -gt 0 ]]; then
            joined="${parts[0]}"
            for ((_i=1; _i<${#parts[@]}; _i++)); do joined+=" / ${parts[_i]}"; done
            msg+=" ${joined}"
          fi
          msg+=", or start fresh."

          mkdir -p "$STATE_DIR" 2>/dev/null
          # MSYS_NO_PATHCONV: on Git-bash, MSYS rewrites POSIX-path-like substrings in
          # arguments to native jq.exe (an embedded /tmp/... in the offer becomes
          # C:/Users/...). Disable it so the offer text is emitted verbatim. No-op off Windows.
          MSYS_NO_PATHCONV=1 jq -nc --arg c "$msg" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit", additionalContext:$c}}'
          # Deliberately touched here — on first ACTUAL offer — not unconditionally
          # on prompt 1. This lets a slow, backgrounded SessionStart pointer write that
          # lands between prompt 1 and prompt 2 still produce the single offer on
          # prompt 2. Do NOT move this to an unconditional first-prompt touch; that
          # reintroduces missed offers on that race.
          touch "$marker" 2>/dev/null
        fi
      fi
    fi
  fi
fi

# --- 2. THEN WRITE the current session's pointer (always) --------------
if [[ -n "$transcript_path" && -n "$cwd" ]]; then
  "$HERE/np-resume-write.sh" --throttle --session "$sid" --transcript "$transcript_path" --cwd "$cwd" >/dev/null 2>&1 || true
fi

exit 0
