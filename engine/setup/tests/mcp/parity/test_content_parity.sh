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

# Use a path form that BOTH Git-bash and the native-Windows Python resolve to the
# SAME location, so fixtures are byte-identical across runtimes (no MSYS POSIX vs
# Windows dialect split, no config-file path the native Python can't stat). On
# Windows that's the mixed form (C:/Users/...); off Windows it's a no-op.
if command -v cygpath >/dev/null 2>&1; then tmp="$(cygpath -m "$tmp")"; fi

# Isolate HOME so ~/.config/nervepack/{content-dir,team-dir,toggles.local} are ours,
# and keep toggle resolution hermetic (empty conf -> default-on, controlled local).
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack"
: > "$tmp/toggles.conf"
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"
: > "$NP_TOGGLES_LOCAL"
mkdir -p "$tmp/personal" "$tmp/team"

# Canonicalize path lines for a cross-dialect compare. Under Git-bash the bash
# resolver emits POSIX paths (/tmp/x, /d/a/...) while the native-Windows Python
# child receives MSYS-converted env/argv and emits Windows paths (C:/Users/...,
# with 8.3 short names like RUNNER~1) — the SAME directory in two dialects. Fold
# both to a canonical long Windows form (lowercased, since Windows paths are
# case-insensitive) so equality means "same target dir", not "same bytes". No-op
# off Windows (no cygpath) — there byte-identity holds and is asserted exactly.
_canon() {
  command -v cygpath >/dev/null 2>&1 || { cat; return; }
  local ln c
  while IFS= read -r ln || [[ -n "$ln" ]]; do
    # -u (to POSIX) reliably accepts BOTH POSIX (/d/a/..) and backslash-Windows
    # (D:\a\..) input, folding the same location to one form. Lowercase for the
    # case-insensitive FS. Fall back to the raw line if cygpath can't convert.
    c="$(cygpath -u "$ln" 2>/dev/null)"; [[ -n "$c" ]] || c="$ln"
    printf '%s\n' "$c" | tr 'A-Z' 'a-z'
  done
}

# $1=fn  $2=py subcommand  $3=source-lib (content|layer)  [$4=path -> canonicalize]
_cmp() {
  local lib="$CLIB"; [[ "$3" == layer ]] && lib="$LLIB"
  ( source "$lib"; "$1" ) > "$tmp/b.out" 2>/dev/null; local bx=$?
  python3 "$PYC" "$2" > "$tmp/p.out" 2>/dev/null; local px=$?
  if [[ "${4:-}" == path ]]; then
    _canon < "$tmp/b.out" > "$tmp/b.cmp"; _canon < "$tmp/p.out" > "$tmp/p.cmp"
  else
    cp "$tmp/b.out" "$tmp/b.cmp"; cp "$tmp/p.out" "$tmp/p.cmp"
  fi
  if ! cmp -s "$tmp/b.cmp" "$tmp/p.cmp" || [[ "$bx" != "$px" ]]; then
    echo "FAIL $1/$2: bash=[$(cat "$tmp/b.out")](exit $bx) python=[$(cat "$tmp/p.out")](exit $px)"
    fails=$((fails+1))
  fi
}
cmp_c() { _cmp "$1" "$2" content "${3:-}"; }   # content-lib fn vs py subcommand
cmp_l() { _cmp "$1" "$2" layer   "${3:-}"; }   # layer-lib fn (sources toggle+content) vs py subcommand

# --- Case A: NP_CONTENT_DIR env, existing ----------------------------------
export NP_CONTENT_DIR="$tmp/personal"; unset NP_TEAM_DIR
cmp_c np_content_dir content_dir path
cmp_c np_content_dir_origin content_origin
cmp_c np_content_is_explicit is_explicit
cmp_c np_team_dir team_dir path
cmp_c np_team_dir_origin team_origin

# --- Case B: NP_CONTENT_DIR env, NONEXISTENT (explicit-but-missing) ---------
export NP_CONTENT_DIR="$tmp/nope"
cmp_c np_content_dir content_dir path          # both: no stdout, exit 1
cmp_c np_content_dir_origin content_origin # still env
cmp_l np_content_layers content_layers path     # personal fails -> empty
cmp_l np_merge_roots merge_roots path

# --- Case C: config-file content-dir ---------------------------------------
unset NP_CONTENT_DIR
printf '%s\n' "$tmp/personal" > "$HOME/.config/nervepack/content-dir"
cmp_c np_content_dir content_dir path
cmp_c np_content_dir_origin content_origin   # config
cmp_c np_content_is_explicit is_explicit

# --- Case D: nothing set -> engine-root fallback (implicit) -----------------
rm -f "$HOME/.config/nervepack/content-dir"
cmp_c np_content_dir content_dir path             # both print the engine repo root
cmp_c np_content_dir_origin content_origin   # default
cmp_c np_content_is_explicit is_explicit     # both exit 1

# --- Case E: team stack, team toggle ON, override mode ----------------------
export NP_CONTENT_DIR="$tmp/personal" NP_TEAM_DIR="$tmp/team"
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"
cmp_c np_team_dir team_dir path
cmp_c np_team_dir_origin team_origin
cmp_l np_content_layers content_layers path       # team, personal
cmp_l np_merge_mode merge_mode               # override (default)
cmp_l np_merge_roots merge_roots path             # team, personal

# multi-team list: np_team_dirs parity (order, trim, dedup)
mkdir -p "$tmp/team2" "$tmp/team3"
export NP_TEAM_DIR="$tmp/team, $tmp/team2 ,$tmp/team3"
cmp_c np_team_dirs team_dirs path
cmp_c np_team_dir team_dir path                   # first entry
cmp_l np_content_layers content_layers path       # team,team2,team3,personal
cmp_l np_merge_roots merge_roots path

# team-only mode WITH >1 team still configured: exercises Python's roots[:-1]
# slice vs bash's loop for the multi-team case (Case F below only ever runs
# team-only after NP_TEAM_DIR is restored to a single team dir).
printf 'team=on\nteam.merge=team-only\n' > "$NP_TOGGLES_LOCAL"
cmp_l np_merge_roots merge_roots path             # team,team2,team3 (personal dropped)
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"          # restore override mode

export NP_TEAM_DIR="$tmp/team"                    # restore single-team for later cases

# --- Case F: team-only merge mode -------------------------------------------
printf 'team=on\nteam.merge=team-only\n' > "$NP_TOGGLES_LOCAL"
cmp_l np_merge_mode merge_mode
cmp_l np_merge_roots merge_roots path             # just team

# --- Case G: team toggle OFF -> team excluded even though NP_TEAM_DIR set ----
printf 'team=off\n' > "$NP_TOGGLES_LOCAL"
cmp_l np_content_layers content_layers path       # personal only
cmp_l np_merge_roots merge_roots path

# --- Case H: team configured but dir missing --------------------------------
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"
export NP_TEAM_DIR="$tmp/team-nope"
cmp_c np_team_dir team_dir path                   # both: no stdout, exit 1
cmp_l np_content_layers content_layers path       # personal only

# --- Case I: invalid team.merge value -> validated to override --------------
export NP_TEAM_DIR="$tmp/team"
printf 'team=on\nteam.merge=bogus\n' > "$NP_TOGGLES_LOCAL"
cmp_l np_merge_mode merge_mode
cmp_l np_merge_roots merge_roots path

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_content_parity: $fails parity mismatch(es)"
  exit 1
fi
echo "PASS test_content_parity"
