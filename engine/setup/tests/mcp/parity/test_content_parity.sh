#!/usr/bin/env bash
# A/B parity: np_content.py (the Python port) must produce byte-identical stdout
# and exit code to np-content-lib.sh + np-layer-lib.sh (the bash originals)
# across the content-overlay resolution table: env vs config-file vs engine-root
# fallback, explicit-but-missing, the team>personal stack under each team.merge
# mode, and the team toggle gating the stack.
#
# Requires bash (compares against it), so it runs on Linux + the Git-bash Windows
# lane, not the bash-free lane.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
CLIB="$SETUP/np-content-lib.sh"
LLIB="$SETUP/np-layer-lib.sh"
PYC="$SETUP/np_content.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_content_parity: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0

# Isolate HOME so ~/.config/nervepack/{content-dir,team-dir,toggles.local} are ours,
# and keep toggle resolution hermetic (empty conf -> default-on, controlled local).
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack"
: > "$tmp/toggles.conf"
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"
: > "$NP_TOGGLES_LOCAL"
mkdir -p "$tmp/personal" "$tmp/team"

# Compare a content-lib function against a python subcommand (stdout bytes + exit).
cmp_c() {  # $1=content-lib fn  $2=py subcommand
  ( source "$CLIB"; "$1" ) > "$tmp/b.out" 2>/dev/null; local bx=$?
  python3 "$PYC" "$2" > "$tmp/p.out" 2>/dev/null; local px=$?
  if ! cmp -s "$tmp/b.out" "$tmp/p.out" || [[ "$bx" != "$px" ]]; then
    echo "FAIL $1/$2: bash=[$(cat "$tmp/b.out")](exit $bx) python=[$(cat "$tmp/p.out")](exit $px)"
    fails=$((fails+1))
  fi
}
# Compare a layer-lib function (sources toggle+content) against a python subcommand.
cmp_l() {  # $1=layer-lib fn  $2=py subcommand
  ( source "$LLIB"; "$1" ) > "$tmp/b.out" 2>/dev/null; local bx=$?
  python3 "$PYC" "$2" > "$tmp/p.out" 2>/dev/null; local px=$?
  if ! cmp -s "$tmp/b.out" "$tmp/p.out" || [[ "$bx" != "$px" ]]; then
    echo "FAIL $1/$2: bash=[$(cat "$tmp/b.out")](exit $bx) python=[$(cat "$tmp/p.out")](exit $px)"
    fails=$((fails+1))
  fi
}

# --- Case A: NP_CONTENT_DIR env, existing ----------------------------------
export NP_CONTENT_DIR="$tmp/personal"; unset NP_TEAM_DIR
cmp_c np_content_dir content_dir
cmp_c np_content_dir_origin content_origin
cmp_c np_content_is_explicit is_explicit
cmp_c np_team_dir team_dir
cmp_c np_team_dir_origin team_origin

# --- Case B: NP_CONTENT_DIR env, NONEXISTENT (explicit-but-missing) ---------
export NP_CONTENT_DIR="$tmp/nope"
cmp_c np_content_dir content_dir          # both: no stdout, exit 1
cmp_c np_content_dir_origin content_origin # still env
cmp_l np_content_layers content_layers     # personal fails -> empty
cmp_l np_merge_roots merge_roots

# --- Case C: config-file content-dir ---------------------------------------
unset NP_CONTENT_DIR
printf '%s\n' "$tmp/personal" > "$HOME/.config/nervepack/content-dir"
cmp_c np_content_dir content_dir
cmp_c np_content_dir_origin content_origin   # config
cmp_c np_content_is_explicit is_explicit

# --- Case D: nothing set -> engine-root fallback (implicit) -----------------
rm -f "$HOME/.config/nervepack/content-dir"
cmp_c np_content_dir content_dir             # both print the engine repo root
cmp_c np_content_dir_origin content_origin   # default
cmp_c np_content_is_explicit is_explicit     # both exit 1

# --- Case E: team stack, team toggle ON, override mode ----------------------
export NP_CONTENT_DIR="$tmp/personal" NP_TEAM_DIR="$tmp/team"
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"
cmp_c np_team_dir team_dir
cmp_c np_team_dir_origin team_origin
cmp_l np_content_layers content_layers       # team, personal
cmp_l np_merge_mode merge_mode               # override (default)
cmp_l np_merge_roots merge_roots             # team, personal

# --- Case F: team-only merge mode -------------------------------------------
printf 'team=on\nteam.merge=team-only\n' > "$NP_TOGGLES_LOCAL"
cmp_l np_merge_mode merge_mode
cmp_l np_merge_roots merge_roots             # just team

# --- Case G: team toggle OFF -> team excluded even though NP_TEAM_DIR set ----
printf 'team=off\n' > "$NP_TOGGLES_LOCAL"
cmp_l np_content_layers content_layers       # personal only
cmp_l np_merge_roots merge_roots

# --- Case H: team configured but dir missing --------------------------------
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"
export NP_TEAM_DIR="$tmp/team-nope"
cmp_c np_team_dir team_dir                   # both: no stdout, exit 1
cmp_l np_content_layers content_layers       # personal only

# --- Case I: invalid team.merge value -> validated to override --------------
export NP_TEAM_DIR="$tmp/team"
printf 'team=on\nteam.merge=bogus\n' > "$NP_TOGGLES_LOCAL"
cmp_l np_merge_mode merge_mode
cmp_l np_merge_roots merge_roots

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_content_parity: $fails parity mismatch(es)"
  exit 1
fi
echo "PASS test_content_parity"
