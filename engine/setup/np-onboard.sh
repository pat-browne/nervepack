#!/usr/bin/env bash
# Full Claude-Code onboard, in one idempotent run: link the skills, wire every
# lifecycle hook, install the scheduler for this OS, register the MCP server, and
# verify with the doctor. Each step is a numbered setup script that is itself
# idempotent; this is the single orchestrator that runs them in order, so the MCP
# `nervepack_onboard` tool and a bare-CLI onboard share one entry point.
#
# Safe to re-run. A failing step logs a warning and the run continues (the doctor
# at the end reports the real, resolved state). The scheduler backend is chosen by
# `uname`: launchd on macOS, Task Scheduler on native Windows (Git-bash), cron
# elsewhere.
#
# Usage:  np-onboard.sh              # wire this host, then run the doctor
# Config: reads NP_CONTENT_DIR / ~/.config/nervepack/{content-dir,team-dir} like the
#         rest of nervepack — set those first (or via the MCP tool's args) to point
#         at your overlay before onboarding.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

step() {  # $1 = script basename (relative to HERE), $2.. = args
  local s="$1"; shift
  [[ -e "$HERE/$s" ]] || { echo "  · skip $s (not present)"; return 0; }
  echo "── $s"
  if ! bash "$HERE/$s" "$@"; then
    echo "  ! $s exited non-zero — continuing (the doctor will report the gap)" >&2
  fi
}

# 1. Knowledge + the dashboard data bridge.
step 30-link-skills.sh
step 35-link-dashboard-data.sh

# 2. Every lifecycle hook installer (5x). Globbed + numeric-sorted so a newly added
#    hook is picked up automatically, in order.
for f in "$HERE"/5[0-9]-install-*.sh; do
  [[ -e "$f" ]] && step "$(basename "$f")"
done

# 3. The scheduler, by OS.
case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin)               step 70-install-memory-launchd.sh ;;
  MINGW*|MSYS*|CYGWIN*) step 70-install-memory-schtasks.sh ;;
  *)                    step 70-install-memory-cron.sh ;;
esac

# 4. Verify. The doctor's exit status is this script's status.
echo "── np-doctor.sh"
bash "$HERE/np-doctor.sh"
