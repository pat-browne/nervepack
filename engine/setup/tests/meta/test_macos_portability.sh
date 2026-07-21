#!/usr/bin/env bash
# np-test: portability | property
# Guards the macOS-runtime surface: the runtime hook/cron scripts (everything in
# engine/setup/ EXCEPT the numbered NN-*.sh Ubuntu bootstrappers, which are
# deliberately Linux/apt-only) must not use GNU-coreutils-only constructs that
# break on a stock macOS box (BSD stat/find, default bash 3.2). nervepack onboards
# any agentic host via the onboard contract, so these scripts run unported on a Mac.
# Red→green for the stat -c / find -printf port; locks in the regression.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"

# GNU-only / BSD-incompatible patterns, each with the portable alternative to use.
#   stat -c            -> stat -f (BSD) — wrap in a try-GNU-then-BSD helper, or wc -c for size
#   find ... -printf   -> not in BSD find — prefix mtime via a stat helper, then sort
#   readlink -f        -> not in BSD readlink — use a pwd -P resolve loop
#   grep -P            -> not in BSD grep — use grep -E / awk
#   date -d / --date   -> not in BSD date — pass epoch, or compute differently
PATTERNS='stat -c|find[^|]*-printf|readlink -f|grep -P|date -d |date --date'

# bash 4+ -only constructs that break on stock macOS bash 3.2 (its `/bin/bash`):
#   declare -A / local -A  -> associative arrays; use parallel arrays + a linear upsert
#   mapfile / readarray    -> read into the array with `while IFS= read -r x; do arr+=("$x"); done`
# Unlike the GNU-coreutils set above, these break in EVERY script that can run on a
# Mac — including the numbered onboarding/launchd scripts (30/35/60/71-77), which is
# exactly why the bug that motivated this lived in 30-link-skills.sh. So the bash-3.2
# scan is NOT exempted for numbered scripts. There is no Linux-only bootstrapper left
# to exempt either: the apt/brew baselines, the scheduler installers, and the
# onboard orchestrator are all Python now (np_bootstrap.py / np_scheduler_install.py
# / np_onboard.py), so this list stays empty until a genuinely bash, Linux-only
# script exists again.
BASH4='(declare|local) -A|^[[:space:]]*(mapfile|readarray)'
BASH4_LINUX_ONLY=''

fail=0
while IFS= read -r f; do
  base="$(basename "$f")"

  # --- GNU-coreutils check: numbered NN-*.sh bootstrappers exempt (legacy scope) ---
  # Flag real, executable GNU-only usage only: drop comment-only lines, and drop
  # the deliberate try-GNU-then-BSD fallback idiom (`stat -c ... || stat -f`).
  if [[ ! "$base" =~ ^[0-9] ]]; then
    hits="$(grep -nE "$PATTERNS" "$f" 2>/dev/null \
      | grep -vE ':[[:space:]]*#' \
      | grep -vE 'stat -c.*\|\|.*stat -f' \
      || true)"
    if [[ -n "$hits" ]]; then
      echo "FAIL: GNU-only construct in macOS-runtime script $base:"
      echo "$hits"
      fail=1
    fi
  fi

  # --- bash 3.2 check: every script except the Linux-only bootstrappers ---
  # Strip trailing comments first so prose naming a builtin doesn't false-positive.
  if [[ "$BASH4_LINUX_ONLY" != *" $base "* ]]; then
    b4="$(sed 's/#.*//' "$f" | grep -nE "$BASH4" 2>/dev/null || true)"
    if [[ -n "$b4" ]]; then
      echo "FAIL: bash 4+ construct (breaks on stock macOS bash 3.2) in $base:"
      echo "$b4"
      fail=1
    fi
  fi
done < <(find "$SETUP" -maxdepth 1 -name '*.sh' -type f | sort)

(( fail )) && exit 1
echo "PASS test_macos_portability"
