#!/usr/bin/env bash
# np-test: resume|sessionstart
# Exercises np-resume-sessionstart.sh: reconstructs the resume pointer for the
# most-recent COMPLETED PRIOR session at SessionStart — skipping the current
# (active) session and any agent-* subagent transcript, and requiring the
# candidate to be settled (mtime older than MIN_AGE_SEC). Hermetic: builds its
# own tmp CLAUDE_PROJECTS_DIR + git repo + toggles files, never touches the real
# $HOME/.cache/nervepack or ~/.config/nervepack.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../../../.." && pwd)"   # tests/resume -> setup -> engine -> repo root
SCRIPT="$NP/engine/setup/np-resume-sessionstart.sh"

fail() { echo "FAIL: $*"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- hermetic env: toggles + resume writer's own knobs + a fake projects dir ---
export NP_TOGGLES_CONF="$tmp/toggles-empty.conf"
export NP_TOGGLES_LOCAL="$tmp/toggles-local-none"
export CLAUDE_PROJECTS_DIR="$tmp/projects"
export NP_RESUME_POINTER="$tmp/pointer.json"
export NP_RESUME_STAMP="$tmp/last-write"
export NP_RESUME_LOG="$tmp/resume.log"

mkdir -p "$CLAUDE_PROJECTS_DIR/proj"

# portable replacement for `touch -d 'N minutes ago'` (BSD touch has no relative -d):
# GNU touch accepts @epoch; BSD touch needs -t with an epoch formatted via BSD `date -r`.
touch_ago() {  # $1=seconds-ago  $2=file
  local e=$(( $(date +%s) - $1 ))
  touch -d "@$e" "$2" 2>/dev/null || touch -t "$(date -r "$e" +%Y%m%d%H%M.%S)" "$2"
}

# --- a real git repo the settled PRIOR (newer) session's transcript points at ---
REPO="$tmp/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email "test@example.com"
git -C "$REPO" config user.name "Test"
echo "hello" > "$REPO/README.md"
git -C "$REPO" add README.md
git -C "$REPO" commit -q -m "baseline"
REPO_HEAD="$(git -C "$REPO" rev-parse --short HEAD)"
REPO_BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"

# --- a SECOND, distinct git repo the settled OLDER PRIOR session points at —
# exists solely to make the newest-first ordering non-vacuous: with two settled
# non-agent prior candidates at different mtimes, a `sort -rn` -> `sort -n`
# regression (oldest-first) would pick this one instead and the assertions below
# would fail. ---
OLDER_REPO="$tmp/older-repo"
mkdir -p "$OLDER_REPO"
git -C "$OLDER_REPO" init -q -b main
git -C "$OLDER_REPO" config user.email "test@example.com"
git -C "$OLDER_REPO" config user.name "Test"
echo "older" > "$OLDER_REPO/README.md"
git -C "$OLDER_REPO" add README.md
git -C "$OLDER_REPO" commit -q -m "older baseline"

CURRENT_SID="99999999-current"
PRIOR_SID="88888888-prior"
OLDER_PRIOR_SID="66666666-older-prior"
AGENT_SID="agent-77777777"
CURRENT_CWD="$tmp/currentcwd"   # deliberately NOT $REPO, so a pointer citing $REPO
mkdir -p "$CURRENT_CWD"          # proves it came from the prior transcript, not the payload

# --- fixture 1: the CURRENT (active) session — fresh mtime, must be skipped ---
active_f="$CLAUDE_PROJECTS_DIR/proj/$CURRENT_SID.jsonl"
printf '%s\n' '{"type":"user","cwd":"'"$CURRENT_CWD"'","message":{"role":"user","content":"hi"}}' > "$active_f"
# left at "now" mtime deliberately — an active session is always recently written

# --- fixture 2: an agent-* subagent transcript — settled but never a real session ---
agent_f="$CLAUDE_PROJECTS_DIR/proj/$AGENT_SID.jsonl"
printf '%s\n' '{"type":"user","cwd":"'"$REPO"'","message":{"role":"user","content":"hi"}}' > "$agent_f"
touch_ago 600 "$agent_f"

# --- fixture 3: the settled PRIOR (NEWER) session — real cwd + a genuine typed user line ---
prior_f="$CLAUDE_PROJECTS_DIR/proj/$PRIOR_SID.jsonl"
printf '%s\n%s\n' \
  '{"type":"user","cwd":"'"$REPO"'","message":{"role":"user","content":"hi"}}' \
  '{"type":"user","promptSource":"typed","message":{"role":"user","content":"resume the prior session work"}}' \
  > "$prior_f"
touch_ago 600 "$prior_f"

# --- fixture 4: a settled OLDER PRIOR session — also non-agent, also settled
# (mtime > MIN_AGE_SEC), but strictly older than fixture 3 and pointing at a
# different repo/cwd/session id. Both fixture 3 and fixture 4 are eligible
# candidates; only the newest-first scan order distinguishes them. ---
older_prior_f="$CLAUDE_PROJECTS_DIR/proj/$OLDER_PRIOR_SID.jsonl"
printf '%s\n%s\n' \
  '{"type":"user","cwd":"'"$OLDER_REPO"'","message":{"role":"user","content":"hi"}}' \
  '{"type":"user","promptSource":"typed","message":{"role":"user","content":"the older session work"}}' \
  > "$older_prior_f"
touch_ago 1200 "$older_prior_f"

# === RUN 1: SessionStart payload for the current session -> pointer describes
# the NEWER of the two settled priors (fixture 3), never the older (fixture 4) ===
printf '{"session_id":"%s","cwd":"%s"}' "$CURRENT_SID" "$CURRENT_CWD" | bash "$SCRIPT"

[[ -f "$NP_RESUME_POINTER" ]] || fail "no pointer written for the settled prior session"
jq -e --arg v "$PRIOR_SID" '.session_id == $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "pointer session_id is not the prior session (got $(jq -r .session_id "$NP_RESUME_POINTER" 2>/dev/null))"
jq -e --arg v "$CURRENT_SID" '.session_id != $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "pointer session_id is the CURRENT session — must describe the prior one"
jq -e --arg v "$AGENT_SID" '.session_id != $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "pointer session_id is the agent-* transcript — must never be picked"
jq -e --arg v "$OLDER_PRIOR_SID" '.session_id != $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "pointer session_id is the OLDER prior session — ordering picked oldest-first instead of newest-first (sort direction regression?)"
jq -e --arg v "$REPO" '.cwd == $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "pointer cwd should be the PRIOR session's repo, got $(jq -r .cwd "$NP_RESUME_POINTER" 2>/dev/null)"
jq -e --arg v "$OLDER_REPO" '.cwd != $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "pointer cwd is the OLDER prior session's repo — must be the newer one"
jq -e --arg v "$REPO_HEAD" '.git_head == $v' "$NP_RESUME_POINTER" >/dev/null || fail "git_head mismatch"
jq -e --arg v "$REPO_BRANCH" '.git_branch == $v' "$NP_RESUME_POINTER" >/dev/null || fail "git_branch mismatch"
jq -e --arg v "$prior_f" '.transcript_path == $v' "$NP_RESUME_POINTER" >/dev/null || fail "transcript_path mismatch"

echo "PASS: pointer describes the NEWER settled prior session, not current/agent/older-prior"

# === RUN 2: no settled prior session (only active + agent) -> no pointer, exit 0 ===
rm -f "$NP_RESUME_POINTER" "$prior_f" "$older_prior_f"
printf '{"session_id":"%s","cwd":"%s"}' "$CURRENT_SID" "$CURRENT_CWD" | bash "$SCRIPT"
rc=$?
[[ "$rc" == 0 ]] || fail "script did not exit 0 with no prior session available (rc=$rc)"
[[ -f "$NP_RESUME_POINTER" ]] && fail "a pointer was written despite no settled prior session existing"

echo "PASS: no prior session -> no pointer, exit 0"

echo "PASS test_resume_sessionstart"
