#!/usr/bin/env bash
# np_team_dir / np_team_dir_origin resolution.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../../np-content-lib.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"   # isolate ~/.config
mkdir -p "$tmp/team" "$tmp/cfgteam" "$tmp/.config/nervepack"

# 1) env set + dir exists -> prints it, origin=env
out="$(NP_TEAM_DIR="$tmp/team" bash -c "source '$LIB'; np_team_dir")"
[[ "$out" == "$tmp/team" ]] || { echo "FAIL: env dir: got '$out'"; exit 1; }
o="$(NP_TEAM_DIR="$tmp/team" bash -c "source '$LIB'; np_team_dir_origin")"
[[ "$o" == env ]] || { echo "FAIL: origin env: got '$o'"; exit 1; }

# 2) env unset, config file present -> prints config dir, origin=config
printf '%s\n' "$tmp/cfgteam" > "$tmp/.config/nervepack/team-dir"
out="$(bash -c "source '$LIB'; np_team_dir")"
[[ "$out" == "$tmp/cfgteam" ]] || { echo "FAIL: config dir: got '$out'"; exit 1; }
o="$(bash -c "source '$LIB'; np_team_dir_origin")"
[[ "$o" == config ]] || { echo "FAIL: origin config: got '$o'"; exit 1; }

# 3) neither -> nothing + non-zero, origin=none
rm -f "$tmp/.config/nervepack/team-dir"
if out="$(bash -c "source '$LIB'; np_team_dir")"; then echo "FAIL: unconfigured returned 0"; exit 1; fi
[[ -z "$out" ]] || { echo "FAIL: unconfigured printed '$out'"; exit 1; }
o="$(bash -c "source '$LIB'; np_team_dir_origin")"
[[ "$o" == none ]] || { echo "FAIL: origin none: got '$o'"; exit 1; }

# 4) explicit env path missing -> error + non-zero
if NP_TEAM_DIR="$tmp/nope" bash -c "source '$LIB'; np_team_dir" 2>/dev/null; then
  echo "FAIL: missing explicit path returned 0"; exit 1; fi

echo "PASS test_team_dir"
