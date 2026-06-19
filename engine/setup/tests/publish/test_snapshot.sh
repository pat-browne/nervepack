#!/usr/bin/env bash
# Regression for np-publish-snapshot.sh: a clean committed tree exports + scans clean
# (exit 0); a tree with a planted secret blocks (exit 1); a bad ref is a setup error
# (exit 2). Black-box via NP_PUBLISH_REPO against throwaway git repos — never touches
# the real engine tree.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$(cd "$HERE/../../../.." && pwd)/publish/np-publish-snapshot.sh"
[[ -f "$HELPER" ]] || { echo "FAIL: helper not found at $HELPER"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkgit() { # mkgit <dir>: init a repo and make one commit of whatever's staged
  git -C "$1" init -q
  git -C "$1" add -A
  git -C "$1" -c user.email=t@t.test -c user.name=test commit -q -m init
}

# 1. Clean committed tree -> exit 0.
clean="$tmp/clean"; mkdir -p "$clean/engine/setup"
printf '#!/usr/bin/env bash\necho ok\n' > "$clean/engine/setup/foo.sh"
mkgit "$clean"
if ! NP_PUBLISH_REPO="$clean" bash "$HELPER" >/dev/null 2>&1; then
  echo "FAIL: clean tree should pass (exit 0)"; exit 1
fi

# 2. Committed secret -> exit 1 (the gate must block).
dirty="$tmp/dirty"; mkdir -p "$dirty"
printf 'aws key AKIAABCDEFGHIJKLMNOP and box 192.168.0.113\n' > "$dirty/notes.md"
mkgit "$dirty"
NP_PUBLISH_REPO="$dirty" bash "$HELPER" >/dev/null 2>&1
rc=$?
[[ "$rc" == 1 ]] || { echo "FAIL: planted secret should block with exit 1, got $rc"; exit 1; }

# 3. Scrubbing it in the WORKING TREE is not enough — the gate scans the committed ref.
#    (Proves the history-free guarantee: a dirty-worktree fix doesn't fool the gate.)
printf 'box at <placeholder>\n' > "$dirty/notes.md"   # fix worktree only, do NOT commit
NP_PUBLISH_REPO="$dirty" bash "$HELPER" >/dev/null 2>&1
rc=$?
[[ "$rc" == 1 ]] || { echo "FAIL: uncommitted scrub must still block (gate scans HEAD), got $rc"; exit 1; }
#    ...but once committed, it passes.
git -C "$dirty" add -A && git -C "$dirty" -c user.email=t@t.test -c user.name=test commit -q -m scrub
if ! NP_PUBLISH_REPO="$dirty" bash "$HELPER" >/dev/null 2>&1; then
  echo "FAIL: committed scrub should pass (exit 0)"; exit 1
fi

# 4. Bad ref -> setup error (exit 2).
NP_PUBLISH_REPO="$clean" bash "$HELPER" no-such-ref >/dev/null 2>&1
rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: bad ref should be a setup error (exit 2), got $rc"; exit 1; }

echo "PASS test_snapshot"
