#!/usr/bin/env bash
# Team-layer pull is tied to a REAL engine-sync path, not to every exit.
#  1. On a genuine engine-sync outcome (engine up-to-date), a behind team clone
#     fast-forwards to its origin.
#  2. On a deliberate early-out (sync toggle OFF), the team clone is NOT touched
#     — the regression the trap-based trigger used to cause.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
git config --global user.email t@t; git config --global user.name t; git config --global init.defaultBranch main

# A real engine checkout, up-to-date with its origin, so the engine sync runs to a
# genuine terminal (Case 1: up to date) instead of the not-a-git short-circuit.
git init -q "$tmp/engine-origin"
( cd "$tmp/engine-origin" && echo e>f && git add f && git commit -qm e )
git clone -q "$tmp/engine-origin" "$tmp/Code/nervepack" 2>/dev/null

# Team upstream with two commits; team clone reset one commit behind.
git init -q "$tmp/upstream"; ( cd "$tmp/upstream" && echo a>f && git add f && git commit -qm a && echo b>>f && git commit -qaqm b )
git clone -q "$tmp/upstream" "$tmp/team" 2>/dev/null
( cd "$tmp/team" && git reset -q --hard HEAD~1 )
behind_before="$(git -C "$tmp/team" rev-parse --short HEAD)"

export NP_TEAM_DIR="$tmp/team" NP_TOGGLES_CONF="$S/toggles.conf"

# (1) Real engine-sync path: team clone fast-forwards.
bash "$S/40-sync-nervepack.sh" >/dev/null 2>&1 || true
after="$(git -C "$tmp/team" rev-parse --short HEAD)"
[[ "$after" != "$behind_before" ]] || { echo "FAIL: team repo did not fast-forward on a real engine-sync path ($after)"; exit 1; }

# (2) Regression: with the sync toggle OFF the script early-outs (disabled) — the
# team clone must NOT be fast-forwarded. Put it behind again first.
( cd "$tmp/team" && git reset -q --hard HEAD~1 )
off_before="$(git -C "$tmp/team" rev-parse --short HEAD)"
[[ "$off_before" == "$behind_before" ]] || { echo "FAIL: setup — could not reset team behind ($off_before)"; exit 1; }
mkdir -p "$tmp/.config/nervepack"; printf 'sync=off\n' > "$tmp/.config/nervepack/toggles.local"
bash "$S/40-sync-nervepack.sh" >/dev/null 2>&1 || true
off_after="$(git -C "$tmp/team" rev-parse --short HEAD)"
[[ "$off_after" == "$off_before" ]] || { echo "FAIL: team repo was pulled on the disabled-toggle early-out ($off_after); team sync must not run on deliberate skips"; exit 1; }

echo "PASS test_team_sync"
