#!/usr/bin/env bash
# np_team_dir / np_team_dirs / np_team_dir_origin resolution, driven through the
# Python resolver np_content.py (the sourced bash content lib was retired in phase 18).
#   team_dir     -> prints highest-precedence team dir, exit 1 if none
#   team_dirs    -> one line per dir (precedence order), exit 1 if none
#   team_origin  -> env | config | none
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/../../np_content.py"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"   # isolate ~/.config
mkdir -p "$tmp/team" "$tmp/cfgteam" "$tmp/.config/nervepack"

# 1) env set + dir exists -> prints it, origin=env
out="$(NP_TEAM_DIR="$tmp/team" python3 "$PY" team_dir)"
[[ "$out" == "$tmp/team" ]] || { echo "FAIL: env dir: got '$out'"; exit 1; }
o="$(NP_TEAM_DIR="$tmp/team" python3 "$PY" team_origin)"
[[ "$o" == env ]] || { echo "FAIL: origin env: got '$o'"; exit 1; }

# 2) env unset, config file present -> prints config dir, origin=config
printf '%s\n' "$tmp/cfgteam" > "$tmp/.config/nervepack/team-dir"
out="$(python3 "$PY" team_dir)"
[[ "$out" == "$tmp/cfgteam" ]] || { echo "FAIL: config dir: got '$out'"; exit 1; }
o="$(python3 "$PY" team_origin)"
[[ "$o" == config ]] || { echo "FAIL: origin config: got '$o'"; exit 1; }

# 3) neither -> nothing + non-zero, origin=none
rm -f "$tmp/.config/nervepack/team-dir"
if out="$(python3 "$PY" team_dir)"; then echo "FAIL: unconfigured returned 0"; exit 1; fi
[[ -z "$out" ]] || { echo "FAIL: unconfigured printed '$out'"; exit 1; }
o="$(python3 "$PY" team_origin)"
[[ "$o" == none ]] || { echo "FAIL: origin none: got '$o'"; exit 1; }

# 4) explicit env path missing -> non-zero
if NP_TEAM_DIR="$tmp/nope" python3 "$PY" team_dir 2>/dev/null; then
  echo "FAIL: missing explicit path returned 0"; exit 1; fi

# 5) comma list -> one line per dir, highest-precedence first
mkdir -p "$tmp/t1" "$tmp/t2" "$tmp/t3"
out="$(NP_TEAM_DIR="$tmp/t1,$tmp/t2,$tmp/t3" python3 "$PY" team_dirs | tr '\n' ',')"
[[ "$out" == "$tmp/t1,$tmp/t2,$tmp/t3," ]] || { echo "FAIL: list order: got '$out'"; exit 1; }
# team_dir returns the highest-precedence (first) entry
out="$(NP_TEAM_DIR="$tmp/t1,$tmp/t2,$tmp/t3" python3 "$PY" team_dir)"
[[ "$out" == "$tmp/t1" ]] || { echo "FAIL: team_dir first: got '$out'"; exit 1; }

# 6) whitespace trimmed + exact duplicates deduped
out="$(NP_TEAM_DIR="$tmp/t1 , $tmp/t2 , $tmp/t1" python3 "$PY" team_dirs | tr '\n' ',')"
[[ "$out" == "$tmp/t1,$tmp/t2," ]] || { echo "FAIL: trim/dedup: got '$out'"; exit 1; }

# 7) over-cap (5 entries) -> non-zero + no stdout
mkdir -p "$tmp/t4" "$tmp/t5"
if out="$(NP_TEAM_DIR="$tmp/t1,$tmp/t2,$tmp/t3,$tmp/t4,$tmp/t5" python3 "$PY" team_dirs 2>/dev/null)"; then
  echo "FAIL: over-cap returned 0"; exit 1; fi
[[ -z "$out" ]] || { echo "FAIL: over-cap printed '$out'"; exit 1; }

# 8) a missing dir among valid ones -> non-zero + no stdout
if out="$(NP_TEAM_DIR="$tmp/t1,$tmp/nope,$tmp/t2" python3 "$PY" team_dirs 2>/dev/null)"; then
  echo "FAIL: missing dir returned 0"; exit 1; fi
[[ -z "$out" ]] || { echo "FAIL: missing dir printed '$out'"; exit 1; }

echo "PASS test_team_dir"
