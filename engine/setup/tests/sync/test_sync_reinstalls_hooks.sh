#!/usr/bin/env bash
# np-test: 40-sync-nervepack | happy
# Regression for the incident where yesterday's hook-redirect fix (#101) merged and
# synced cleanly into ~/Code/nervepack, but ~/.claude/settings.json kept running the
# stale pre-fix hook commands for another day — because git pull only updates the
# scripts on disk, and nothing ever re-ran the installers that write settings.json.
#
# Asserts: a real fast-forward merge (NP_SYNC_TARGET behind its origin by one commit
# that adds a new 5x-install-*.sh) re-runs that installer as part of the same sync,
# not just 30-link-skills.sh.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
git config --global init.defaultBranch main 2>/dev/null || true
git config --global user.email t@t 2>/dev/null; git config --global user.name t 2>/dev/null

# Build an "up" origin with an engine/setup/ dir, clone it, then advance "up" by one
# commit that adds a fake installer matching the 5[0-9]-install-*.sh glob.
up="$tmp/up"; local_repo="$tmp/local"
git init -q "$up"
mkdir -p "$up/engine/setup"
: > "$up/engine/setup/.keep"
( cd "$up" && git add -A && git commit -qm init )
git clone -q "$up" "$local_repo"

marker="$tmp/installer-ran"
cat > "$up/engine/setup/59-install-test-marker.sh" <<EOF
#!/usr/bin/env bash
: > "$marker"
EOF
chmod +x "$up/engine/setup/59-install-test-marker.sh"
( cd "$up" && git add -A && git commit -qm "add fake installer" )

NP_SYNC_MODE=exit NP_SYNC_TARGET="$local_repo" NP_SYNC_STATUS="$tmp/status" \
  NP_TOGGLES_CONF="$tmp/nope.conf" NP_TOGGLES_LOCAL="$tmp/nope.local" \
  bash "$S/40-sync-nervepack.sh" >"$tmp/out.log" 2>&1 || true

local_head="$(git -C "$local_repo" rev-parse HEAD)"
up_head="$(git -C "$up" rev-parse HEAD)"
[[ "$local_head" == "$up_head" ]] \
  || { echo "FAIL: local not fast-forwarded (want $up_head got $local_head): $(cat "$tmp/out.log")"; exit 1; }
[[ -e "$marker" ]] \
  || { echo "FAIL: fast-forward did not re-run the pulled 5x-install-*.sh installer: $(cat "$tmp/out.log")"; exit 1; }
echo "PASS test_sync_reinstalls_hooks"
