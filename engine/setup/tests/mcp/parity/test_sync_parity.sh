#!/usr/bin/env bash
# A/B parity: np_sync.py's outcome message must match 40-sync-nervepack.sh's
# across the defensive-sync scenarios — up-to-date (clean/dirty), dirty+behind,
# ahead, fast-forward, diverged, not-a-git, plus the gate/throttle/dry-run early
# exits. Compared modulo the embedded UTC timestamp and the (differing) target
# copy path. The team-layer ff + skill relink are bash-only and out of scope.
#
# Requires bash + git, so it runs on Linux + the Git-bash Windows lane, not the
# bash-free lane.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/40-sync-nervepack.sh"
PY="$SETUP/np_sync.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_sync_parity: no python3"; exit 0; }
command -v git     >/dev/null 2>&1 || { echo "SKIP test_sync_parity: no git"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack"
: > "$tmp/conf"
export NP_TOGGLES_CONF="$tmp/conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"
: > "$NP_TOGGLES_LOCAL"
GI="-c user.email=t@t -c user.name=t -c commit.gpgsign=false"

norm() { sed -E "s/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z/<TS>/g; s#$tmp/t[bp]#<TARGET>#g; s/age [0-9]+s/age <AGE>s/g"; }

# Build $tmp/target as a clone of a bare remote with one commit on main.
init_repo() {
  rm -rf "$tmp/remote.git" "$tmp/seed" "$tmp/target"
  git init -q --bare -b main "$tmp/remote.git"
  git $GI init -q -b main "$tmp/seed"
  git $GI -C "$tmp/seed" commit -q --allow-empty -m c1
  git -C "$tmp/seed" remote add origin "$tmp/remote.git"
  git -C "$tmp/seed" push -q origin main
  git clone -q "$tmp/remote.git" "$tmp/target" 2>/dev/null
  git $GI -C "$tmp/target" config user.email t@t
  git $GI -C "$tmp/target" config user.name t
}
advance_remote() {  # push N empty commits to origin/main from the seed
  git $GI -C "$tmp/seed" commit -q --allow-empty -m "$1"
  git -C "$tmp/seed" push -q origin main
}

# Run both implementations on identical copies of $tmp/target; compare the outcome
# (stdout if any, else the status file), normalized. extra args -> mode (e.g. exit).
compare() {  # $1=label  rest=args passed to both
  local label="$1"; shift
  rm -rf "$tmp/tb" "$tmp/tp"
  [[ -d "$tmp/target" ]] && { cp -r "$tmp/target" "$tmp/tb"; cp -r "$tmp/target" "$tmp/tp"; }
  local bo po
  bo="$(NP_SYNC_TARGET="$tmp/tb" NP_SYNC_STATUS="$tmp/sb" NP_SYNC_STAMP="$tmp/stamp_b" bash "$SH" "$@" 2>/dev/null)"
  [[ -n "$bo" ]] || bo="$(cat "$tmp/sb" 2>/dev/null)"
  po="$(NP_SYNC_TARGET="$tmp/tp" NP_SYNC_STATUS="$tmp/sp" NP_SYNC_STAMP="$tmp/stamp_p" python3 "$PY" "$@" 2>/dev/null)"
  bo="$(printf '%s' "$bo" | norm)"; po="$(printf '%s' "$po" | norm)"
  if [[ "$bo" != "$po" ]]; then
    echo "FAIL [$label]: bash=[$bo] python=[$po]"; fails=$((fails+1))
  fi
}

# --- git scenarios (exit mode = no throttle; outcome lands in the status file) ---
init_repo;                                   compare "up-to-date clean" exit
init_repo; echo x > "$tmp/target/dirty.txt"; compare "up-to-date dirty" exit
init_repo; advance_remote c2;                compare "fast-forward" exit
init_repo; advance_remote c2; echo x > "$tmp/target/dirty.txt"; compare "dirty + behind" exit
init_repo; git $GI -C "$tmp/target" commit -q --allow-empty -m local1; compare "ahead" exit
init_repo; advance_remote c2; git $GI -C "$tmp/target" commit -q --allow-empty -m local1; compare "diverged" exit
init_repo; rm -rf "$tmp/target/.git";        compare "not a git repo" exit

# --- gate / dry-run / throttle early exits (outcome on stdout) ---
init_repo
printf 'sync=off\n' > "$NP_TOGGLES_LOCAL"
compare "disabled toggle" exit
: > "$NP_TOGGLES_LOCAL"
NP_SYNC_DRYRUN=1 compare "dry-run" exit
# throttle: backup mode with a fresh stamp -> within-interval skip. Seed both stamps
# to the same recent time so the reported age matches.
_now="$(date +%s)"; printf '%s' "$_now" > "$tmp/stamp_b"; printf '%s' "$_now" > "$tmp/stamp_p"
NP_SYNC_DRYRUN=0 compare "throttle (backup)"

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_sync_parity: $fails mismatch(es)"; exit 1
fi
echo "PASS test_sync_parity"
