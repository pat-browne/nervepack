#!/usr/bin/env bash
# _np_team_sync ff-syncs EVERY configured team repo, not just the first.
# 40-sync-nervepack.sh sources its own libs and fires _np_team_sync via an EXIT
# trap, so we RUN the script (not source it) with a non-git NP_SYNC_TARGET — the
# engine sync bails on "not a git repo" and exits, firing the trap.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"; mkdir -p "$tmp/.config/nervepack" "$tmp/notgit"
export NP_TOGGLES_CONF="$S/toggles.conf"
printf 'team=on\n' > "$tmp/.config/nervepack/toggles.local"
export NP_TOGGLES_LOCAL="$tmp/.config/nervepack/toggles.local"
git config --global init.defaultBranch main 2>/dev/null || true
git config --global user.email t@t 2>/dev/null; git config --global user.name t 2>/dev/null

# Build two team repos, each a clone one commit BEHIND its origin.
make_behind_repo() { # $1=path
  local up="$1.up"
  git init -q "$up"; ( cd "$up"; echo a > f; git add f; git commit -qm a )
  git clone -q "$up" "$1"
  ( cd "$up"; echo b >> f; git commit -qam b )   # origin now ahead by 1
}
make_behind_repo "$tmp/teamA"; make_behind_repo "$tmp/teamB"
export NP_TEAM_DIR="$tmp/teamA,$tmp/teamB"

# Capture each repo's true upstream HEAD now, before the sync runs. NOTE: we
# assert against this captured SHA rather than the clone's own '@{u}' — the
# remote-tracking ref only updates on an explicit `fetch`, so an UNTOUCHED
# clone's '@{u}' stays frozen at clone time (== its own stale HEAD) and would
# trivially satisfy an is-ancestor check even when never synced at all. That
# false positive is exactly the failure mode this test exists to catch (today,
# only the first team dir is synced — the second is never fetched).
expA="$(git -C "$tmp/teamA.up" rev-parse HEAD)"
expB="$(git -C "$tmp/teamB.up" rev-parse HEAD)"

# Run the sync: engine target is a non-git dir (bails fast); EXIT trap runs the
# team sync over both team repos. NP_SYNC_MODE=exit bypasses the interval throttle.
NP_SYNC_MODE=exit NP_SYNC_TARGET="$tmp/notgit" NP_SYNC_STATUS="$tmp/status" \
  bash "$S/40-sync-nervepack.sh" >/dev/null 2>&1 || true

for r in teamA teamB; do
  case "$r" in teamA) exp="$expA" ;; teamB) exp="$expB" ;; esac
  actual="$(git -C "$tmp/$r" rev-parse HEAD)"
  [[ "$actual" == "$exp" ]] \
    || { echo "FAIL: $r not fast-forwarded to upstream (want $exp got $actual)"; exit 1; }
done
echo "PASS test_team_sync_multi"
