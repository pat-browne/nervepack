#!/usr/bin/env bash
# A/B parity: np_doctor.py's deterministic CORE-check lines (git-sync, toggles,
# content, team, dashboard-data) must be byte-identical to np-doctor.sh's, in a
# controlled environment. The model-seam (llm-cli) and host-adapter checks are
# intentionally NOT compared — the Python doctor reports them N/A (bash-free),
# while the bash doctor runs them; that divergence is by design.
#
# Requires bash + git, so it runs on Linux + the Git-bash Windows lane, not the
# bash-free lane.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/np-doctor.sh"
PY="$SETUP/np_doctor.py"
CAPS="$SETUP/../onboard/capabilities.json"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_doctor_parity: no python3"; exit 0; }
command -v git     >/dev/null 2>&1 || { echo "SKIP test_doctor_parity: no git"; exit 0; }
command -v jq      >/dev/null 2>&1 || { echo "SKIP test_doctor_parity: no jq"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack"

# A throwaway repo with an origin remote (git-sync PASS), a separate content dir
# (content PASS, split layout -> dashboard-data WARN bridge-missing), hermetic toggles.
mkdir -p "$tmp/repo" "$tmp/content"
git -C "$tmp/repo" init -q
git -C "$tmp/repo" remote add origin https://example.test/nervepack.git
: > "$tmp/toggles.conf"
export NP_DIR="$tmp/repo" NP_CONTENT_DIR="$tmp/content" NP_CAPABILITIES="$CAPS"
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"

core='\] (git-sync|toggles|content|team|dashboard-data) '
bash    "$SH" 2>/dev/null | grep -E "$core" > "$tmp/b.out"
python3 "$PY" 2>/dev/null | grep -E "$core" > "$tmp/p.out"

if ! cmp -s "$tmp/b.out" "$tmp/p.out"; then
  echo "FAIL test_doctor_parity: core-check lines differ"
  echo "--- bash ---";   cat "$tmp/b.out"
  echo "--- python ---"; cat "$tmp/p.out"
  exit 1
fi
# Sanity: we actually compared the five core lines (not an empty match).
[[ "$(wc -l < "$tmp/b.out")" -eq 5 ]] || { echo "FAIL test_doctor_parity: expected 5 core lines, got $(wc -l < "$tmp/b.out")"; exit 1; }
echo "PASS test_doctor_parity"
