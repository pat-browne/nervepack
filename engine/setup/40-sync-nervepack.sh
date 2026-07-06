#!/usr/bin/env bash
# Defensive sync. Fetches always; fast-forwards local ONLY when:
#   1. working tree is clean, AND
#   2. local HEAD is a strict ancestor of origin/main (no divergence).
# Never autostashes, never rebases, never touches a dirty working tree.
# Writes outcome to ~/.cache/np-core-sync-status so /np-core-sync and the user
# can see what happened — background hook output is otherwise invisible.
#
# Used by:
#   - the np-core-sync skill (with --verbose to also stdout the status)
#   - the SessionStart hook (50-install-session-hook.sh)
#   - cron / scheduled refinement agents
set -euo pipefail

# Toggle + scheduling: `exit` mode (SessionEnd, primary) always syncs; `backup`
# mode (default, SessionStart) is throttled by sync.interval (default 1 day).
NP_SYNC_MODE="backup"; for _a in "$@"; do [[ "$_a" == "exit" ]] && NP_SYNC_MODE="exit"; done
_npsetup="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_npl="$_npsetup/np-toggle-lib.sh"
_npcl="$_npsetup/np-content-lib.sh"
[[ -r "$_npcl" ]] && source "$_npcl"
if [[ -r "$_npl" ]]; then
  source "$_npl"
  np_enabled sync || { echo "nervepack-sync: disabled via toggle — skipping"; exit 0; }
  _stamp="${NP_SYNC_STAMP:-$HOME/.cache/nervepack/last-sync}"
  if [[ "$NP_SYNC_MODE" != "exit" ]]; then
    _interval="$(np_param sync.interval 86400)"
    if [[ -f "$_stamp" ]]; then
      _age=$(( $(date +%s) - $(cat "$_stamp" 2>/dev/null || echo 0) ))
      [[ "$_age" -lt "$_interval" ]] && { echo "nervepack-sync: within ${_interval}s interval (age ${_age}s) — skipping (backup)"; exit 0; }
    fi
  fi
  mkdir -p "$(dirname "$_stamp")"; date +%s > "$_stamp"
  [[ "${NP_SYNC_DRYRUN:-0}" == "1" ]] && { echo "nervepack-sync: would sync now (mode=$NP_SYNC_MODE)"; exit 0; }
fi

VERBOSE=0
[[ "${1-}" == "--verbose" ]] && VERBOSE=1

NERVEPACK="${NP_SYNC_TARGET:-$HOME/Code/nervepack}"   # override aids the parity port + tests
STATUS="${NP_SYNC_STATUS:-$HOME/.cache/np-core-sync-status}"
mkdir -p "$(dirname "$STATUS")"

# Optional team layer: keep a shared team checkout current (strict-safe: ff-only).
_np_team_sync() {
  declare -f np_enabled >/dev/null 2>&1 || return 0
  declare -f np_team_dir >/dev/null 2>&1 || return 0
  local _team_dir
  np_enabled team || return 0
  _team_dir="$(np_team_dir 2>/dev/null)" || return 0
  git -C "$_team_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  if [[ -z "$(git -C "$_team_dir" status --porcelain 2>/dev/null)" ]]; then
    git -C "$_team_dir" fetch --quiet origin 2>/dev/null \
      && git -C "$_team_dir" merge --ff-only --quiet '@{u}' 2>/dev/null \
      || echo "np-core-sync: team layer not fast-forwarded (diverged/dirty/no upstream) — left as-is" >&2
  else
    echo "np-core-sync: team layer has local edits — skipping pull" >&2
  fi
}

# Arm the team pull HERE — after the deliberate early-outs above (within-interval
# throttle / disabled-via-toggle / dry-run) have already exited. Registering the
# EXIT trap only at this point means those early skips never fire the team fetch
# (the network call the throttle exists to suppress), while every real engine-sync
# outcome below — including the not-a-git path and any `set -e` exit on a status
# write — still triggers it. Non-fatal and self-guarded; never alters the engine
# sync's own exit behavior.
trap '_np_team_sync || true' EXIT

write_status() {
  printf '%s\n' "$*" > "$STATUS"
  [[ "$VERBOSE" == 1 ]] && printf '%s\n' "$*"
}

now() { date -u +%FT%TZ; }

if [[ ! -d "$NERVEPACK/.git" ]]; then
  write_status "np-core-sync: $(now) — $NERVEPACK is not a git repo"
  exit 0
fi

cd "$NERVEPACK"

if ! git fetch --quiet origin main 2>/tmp/np-core-sync.err; then
  write_status "np-core-sync: $(now) — fetch failed: $(cat /tmp/np-core-sync.err)"
  exit 0
fi

local_rev=$(git rev-parse HEAD)
remote_rev=$(git rev-parse origin/main)

# Case 1: up to date
if [[ "$local_rev" == "$remote_rev" ]]; then
  if git diff-index --quiet HEAD -- && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    write_status "np-core-sync: $(now) — up to date ($(git rev-parse --short HEAD))"
  else
    dirty=$(git status --porcelain | wc -l | tr -d ' ')
    write_status "np-core-sync: $(now) — up to date with origin ($dirty uncommitted change(s) in working tree)"
  fi
  exit 0
fi

# Case 2: working tree dirty — never auto-modify
if ! git diff-index --quiet HEAD -- || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  dirty=$(git status --porcelain | wc -l | tr -d ' ')
  behind=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
  write_status "np-core-sync: $(now) — SKIPPED (working tree dirty: $dirty files; $behind remote commits waiting). Commit/stash, then re-run /np-core-sync."
  exit 0
fi

# Case 3: local ahead of remote (nothing to pull, just unpushed commits)
if git merge-base --is-ancestor "$remote_rev" "$local_rev"; then
  ahead=$(git rev-list --count origin/main..HEAD)
  write_status "np-core-sync: $(now) — local is $ahead commit(s) ahead of origin/main. Push when ready."
  exit 0
fi

# Case 4: local is strict ancestor of remote — safe fast-forward
if git merge-base --is-ancestor "$local_rev" "$remote_rev"; then
  pulled=$(git rev-list --count HEAD..origin/main)
  if git merge --ff-only --quiet origin/main 2>/tmp/np-core-sync.err; then
    "$NERVEPACK/engine/setup/30-link-skills.sh" >/dev/null 2>&1 || true
    write_status "np-core-sync: $(now) — fast-forwarded $pulled commit(s) to $(git rev-parse --short HEAD)"
  else
    write_status "np-core-sync: $(now) — ff-only merge failed: $(cat /tmp/np-core-sync.err)"
  fi
  exit 0
fi

# Case 5: diverged — never auto-resolve
ahead=$(git rev-list --count origin/main..HEAD)
behind=$(git rev-list --count HEAD..origin/main)
write_status "np-core-sync: $(now) — DIVERGED ($ahead local-only, $behind remote-only commits). Resolve: cd ~/Code/nervepack && git pull --rebase --autostash"
