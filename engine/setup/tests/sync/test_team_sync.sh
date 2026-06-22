#!/usr/bin/env bash
# A behind team checkout fast-forwards to its origin on sync.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
git config --global user.email t@t; git config --global user.name t; git config --global init.defaultBranch main
# upstream with two commits
git init -q "$tmp/upstream"; ( cd "$tmp/upstream" && echo a>f && git add f && git commit -qm a && echo b>>f && git commit -qaqm b )
# team clone reset one commit behind
git clone -q "$tmp/upstream" "$tmp/team" 2>/dev/null
( cd "$tmp/team" && git reset -q --hard HEAD~1 )
behind_before="$(git -C "$tmp/team" rev-parse --short HEAD)"
export NP_TEAM_DIR="$tmp/team" NP_TOGGLES_CONF="$S/toggles.conf"
bash "$S/40-sync-nervepack.sh" >/dev/null 2>&1 || true
after="$(git -C "$tmp/team" rev-parse --short HEAD)"
[[ "$after" != "$behind_before" ]] || { echo "FAIL: team repo did not fast-forward ($after)"; exit 1; }
echo "PASS test_team_sync"
