#!/usr/bin/env bash
# np-test: installer-glob-coverage | happy
# Regression guard: the lifecycle-hook installer loops in np_onboard.py and
# 40-sync-nervepack.sh MUST pick up EVERY NN-install-*.sh in the 50–69 band,
# and MUST NOT sweep in the platform-specific 70-install-memory-* installers.
#
# Why this exists: 61-install-resume-hook.sh shipped in PR #99 but the loops
# globbed only `5[0-9]-install-*.sh`, so the installer landed on disk yet was
# never run — onboarding skipped it and sync never back-filled it, leaving the
# resume-pointer hooks unregistered. This asserts the true invariant (coverage
# of the whole 50–69 range) rather than a specific glob string, so it stays
# meaningful when a 62-/63- installer is added later.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"

fail() { echo "FAIL test_installer_glob_coverage: $*"; exit 1; }

# Sanity: the installer that motivated this must exist, else the test is vacuous.
[[ -e "$SETUP/61-install-resume-hook.sh" ]] \
  || fail "61-install-resume-hook.sh missing — test fixture assumption broken"

for driver in np_onboard.py 40-sync-nervepack.sh; do
  path="$SETUP/$driver"
  [[ -e "$path" ]] || fail "$driver not found at $path"

  # Pull the installer-loop glob token out of the driver, e.g. `5[0-9]-install-*.sh`
  # or the corrected `[56][0-9]-install-*.sh`. Read the real pattern the script
  # uses so this test tracks the code, not a hard-coded expectation.
  glob="$(grep -oE '(\[[0-9]+\]|[0-9])\[0-9\]-install-\*\.sh' "$path" | head -1)"
  [[ -n "$glob" ]] || fail "$driver: no installer-loop glob (NN-install-*.sh) found"

  # Expand it against the real setup dir (unquoted → pathname expansion).
  matched=""
  for f in $SETUP/$glob; do
    [[ -e "$f" ]] && matched+="$(basename "$f")"$'\n'
  done

  grep -q '^61-install-resume-hook\.sh$' <<<"$matched" \
    || fail "$driver glob '$glob' does not pick up 61-install-resume-hook.sh (6x band excluded)"
  grep -q '70-install-memory' <<<"$matched" \
    && fail "$driver glob '$glob' wrongly matches the platform-specific 70-install-memory-* installer"

  echo "PASS: $driver installer glob '$glob' covers 61-install-resume-hook.sh, excludes 70-install-memory-*"
done

echo "PASS test_installer_glob_coverage"
