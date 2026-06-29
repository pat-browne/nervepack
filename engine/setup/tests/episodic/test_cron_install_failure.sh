#!/usr/bin/env bash
# np-test: memory-cron-install | failure
# Failure path for 70-install-memory-cron.sh when its prerequisite is absent.
# The script opens with an explicit guard:
#     if ! command -v crontab >/dev/null; then echo "... install cron ..." >&2; exit 1; fi
# So with `crontab` removed from PATH it must (a) exit non-zero for THAT reason —
# the clear "crontab not available" message — and (b) NOT proceed to mutate any
# cron state. We run with a PATH that contains the std tools the script needs
# (bash/grep/printf) but deliberately NO crontab, and assert the documented guard
# fires (not some incidental downstream failure).
set -euo pipefail
# cron is the Linux scheduler — on native Windows the backend is Task Scheduler
# (70-install-memory-schtasks.sh). This test also strips PATH to a sandbox bin, which
# breaks Git-bash's own DLL resolution. Not applicable on a Windows kernel; see #38.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "PASS test_cron_install_failure (skipped on Windows — cron is the Linux path)"; exit 0;;
esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../70-install-memory-cron.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# A sandbox bin holding ONLY the coreutils the installer uses, minus crontab.
# Symlink each needed tool from its real location so the script can still run far
# enough to hit (or, if regressed, skip) the crontab guard.
mkdir -p "$tmp/bin"
for t in bash grep printf cat dirname date sed env mkdir; do
  p="$(command -v "$t" 2>/dev/null || true)"
  [[ -n "$p" ]] && ln -s "$p" "$tmp/bin/$t"
done
# Sanity: the sandbox really has no crontab.
PATH="$tmp/bin" command -v crontab >/dev/null 2>&1 && { echo "FAIL: sandbox still exposes crontab"; exit 1; }

rc=0; out="$(PATH="$tmp/bin" bash "$INSTALL" 2>&1)" || rc=$?
[[ "$rc" != 0 ]] || { echo "FAIL: installer exited 0 despite missing crontab: $out"; exit 1; }
echo "$out" | grep -qi 'crontab not available' \
  || { echo "FAIL: missing the documented 'crontab not available' message; got: $out"; exit 1; }
# It must NOT have printed any 'Installed cron entry' line (proves it bailed at the guard,
# not after partially writing cron state).
echo "$out" | grep -q 'Installed cron entry' && { echo "FAIL: proceeded to install despite no crontab: $out"; exit 1; }
echo "PASS test_cron_install_failure"
