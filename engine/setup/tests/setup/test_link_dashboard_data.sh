#!/usr/bin/env bash
# np-test: dashboard-data-bootstrap | happy
# Regression tests for engine/setup/35-link-dashboard-data.sh
# Tests: fresh-clone (no dashboard/data), idempotent re-run, legacy single-repo
# (content dir == engine root), and fail-open on content-dir error.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
SCRIPT="$SETUP/35-link-dashboard-data.sh"

NP="$(cd "$SETUP/../.." && pwd)"

fail() { echo "FAIL: $*"; exit 1; }

# ---------------------------------------------------------------------------
# Case 1: split layout — fresh clone (no dashboard/data). Script must create
# a symlink from <engine>/dashboard/data -> <content>/dashboard/data.
# ---------------------------------------------------------------------------
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

content1="$tmp/content1"
engine1="$tmp/engine1"
mkdir -p "$engine1/dashboard" "$content1"

# Run the script with a fake engine root (NP) and a content dir set via env.
# The script uses HERE to find np-content-lib.sh, but NP is set by
#   NP="$(cd "$HERE/../.." && pwd)"
# — we can't override that without patching the script. Instead, override
# via NP_CONTENT_DIR and rely on the script's own engine root (the real one),
# but redirect the LINK target. We test the script in the real engine,
# pointing at a temp content dir and a temp engine dashboard path,
# by passing the env and checking what the script does in a subshell that
# overrides the LINK path via a wrapper that patches just the relevant vars.

# Strategy: run the REAL script, but with NP_CONTENT_DIR pointing at tmp/content1
# and check that it creates the symlink inside the real engine's dashboard/data
# (since the script hardcodes NP from its own path). To avoid touching the live
# dashboard/data, we use a wrapper that temporarily moves the real link, runs
# the script, captures the result, then restores.

REAL_LINK="$NP/dashboard/data"

# Save the current state of the real link/dir.
saved="$tmp/saved_target"
was_link=0
was_dir=0
if [[ -L "$REAL_LINK" ]]; then
  was_link=1
  readlink "$REAL_LINK" > "$saved"
  rm -f "$REAL_LINK"
elif [[ -d "$REAL_LINK" ]]; then
  was_dir=1
  mv "$REAL_LINK" "$tmp/saved_dir"
fi

restore_link() {
  # Restore the real link to its original state.
  rm -f "$REAL_LINK" 2>/dev/null || true
  if [[ $was_link -eq 1 ]]; then
    # nativestrict so a Windows local run restores a real symlink, not a deep copy.
    MSYS=winsymlinks:nativestrict ln -s "$(cat "$saved")" "$REAL_LINK" 2>/dev/null || true
  elif [[ $was_dir -eq 1 ]]; then
    mv "$tmp/saved_dir" "$REAL_LINK" 2>/dev/null || true
  fi
}
trap 'restore_link; rm -rf "$tmp"' EXIT

# --- Case 1: fresh clone (no dashboard/data at all). ---
# Confirm the link was removed.
[[ ! -e "$REAL_LINK" && ! -L "$REAL_LINK" ]] || fail "setup: REAL_LINK still exists before test"

content1="$tmp/content1"; mkdir -p "$content1"
out1="$(NP_CONTENT_DIR="$content1" bash "$SCRIPT" 2>&1)"
[[ -L "$REAL_LINK" ]] || fail "Case 1: symlink not created; output: $out1"
target1="$(readlink "$REAL_LINK")"
[[ "$target1" == "$content1/dashboard/data" ]] \
  || fail "Case 1: wrong symlink target: $target1 (expected $content1/dashboard/data)"
[[ -d "$target1" ]] || fail "Case 1: target dir was not created: $target1"
echo "  Case 1 OK: fresh clone — symlink created"

# --- Case 2: idempotent re-run — script run again on a correct symlink. ---
out2="$(NP_CONTENT_DIR="$content1" bash "$SCRIPT" 2>&1)"
[[ -L "$REAL_LINK" ]] || fail "Case 2: symlink removed by second run; output: $out2"
target2="$(readlink "$REAL_LINK")"
[[ "$target2" == "$content1/dashboard/data" ]] \
  || fail "Case 2: symlink target changed on second run: $target2"
# No spurious extra symlinks or files.
echo "  Case 2 OK: idempotent re-run — symlink unchanged"

# --- Case 3: wrong symlink target — script must replace it. ---
rm -f "$REAL_LINK"
MSYS=winsymlinks:nativestrict ln -s "/tmp/wrong-target-xyz" "$REAL_LINK"
out3="$(NP_CONTENT_DIR="$content1" bash "$SCRIPT" 2>&1)"
[[ -L "$REAL_LINK" ]] || fail "Case 3: symlink gone after replacement; output: $out3"
target3="$(readlink "$REAL_LINK")"
[[ "$target3" == "$content1/dashboard/data" ]] \
  || fail "Case 3: wrong target after replacement: $target3"
echo "  Case 3 OK: wrong symlink — replaced with correct target"

# --- Case 4: single-repo layout (content dir == engine root) — no symlink. ---
# Remove the current symlink so we start clean.
rm -f "$REAL_LINK"
# With NP_CONTENT_DIR pointing at the ENGINE itself (NP), it's single-repo.
# The script should exit 0 and NOT create a self-referential symlink.
# We need to recreate dashboard/data as a real directory so single-repo check works.
mkdir -p "$REAL_LINK"
out4="$(NP_CONTENT_DIR="$NP" bash "$SCRIPT" 2>&1)"
rc4=$?
[[ $rc4 -eq 0 ]] || fail "Case 4: script exited non-zero ($rc4) in single-repo layout; output: $out4"
[[ ! -L "$REAL_LINK" ]] || fail "Case 4: script created a symlink in single-repo layout (self-referential — should be a no-op)"
[[ -d "$REAL_LINK" ]] || fail "Case 4: real dashboard/data dir was removed in single-repo layout"
echo "  Case 4 OK: single-repo layout — no symlink created"

# --- Case 5: fail-open — bad NP_CONTENT_DIR (dir does not exist). ---
# Remove real dir so we don't hit the single-repo path.
rmdir "$REAL_LINK" 2>/dev/null || rm -rf "$REAL_LINK"
out5="$(NP_CONTENT_DIR="/no/such/content/dir/xyz" bash "$SCRIPT" 2>&1)"
rc5=$?
[[ $rc5 -eq 0 ]] || fail "Case 5: script must exit 0 on bad content dir (fail-open), got $rc5; output: $out5"
[[ ! -L "$REAL_LINK" ]] || fail "Case 5: script created a symlink despite invalid content dir"
echo "  Case 5 OK: fail-open on invalid content dir"

echo "PASS test_link_dashboard_data"
