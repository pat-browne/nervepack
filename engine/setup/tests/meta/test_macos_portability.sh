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

fail=0
while IFS= read -r f; do
  base="$(basename "$f")"
  [[ "$base" =~ ^[0-9] ]] && continue          # NN-*.sh: Linux bootstrappers, exempt
  # Flag real, executable GNU-only usage only: drop comment-only lines, and drop
  # the deliberate try-GNU-then-BSD fallback idiom (`stat -c ... || stat -f`).
  hits="$(grep -nE "$PATTERNS" "$f" 2>/dev/null \
    | grep -vE ':[[:space:]]*#' \
    | grep -vE 'stat -c.*\|\|.*stat -f' \
    || true)"
  if [[ -n "$hits" ]]; then
    echo "FAIL: GNU-only construct in macOS-runtime script $base:"
    echo "$hits"
    fail=1
  fi
done < <(find "$SETUP" -maxdepth 1 -name '*.sh' -type f | sort)

(( fail )) && exit 1
echo "PASS test_macos_portability"
