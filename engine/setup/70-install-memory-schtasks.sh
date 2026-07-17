#!/usr/bin/env bash
# Native-Windows equivalent of 70-install-memory-cron.sh / 70-install-memory-launchd.sh.
# Registers the nervepack maintenance jobs as Windows Task Scheduler tasks (cron does
# not exist on native Windows; schtasks.exe is the built-in scheduler). Runs under
# Git-for-Windows bash and shells out to schtasks.exe — keeping the backbone bash, the
# job logic in the 7x .sh bodies, and the test runnable on Linux CI with a stub
# (mirrors the launchd installer's discipline). Matches the AUTHORITATIVE cron cadence:
#   Daily 08:00 LOCAL — memory-promote    (71)
#   Daily 08:30 LOCAL — episodic-maintain (72)
#   Daily 09:00 LOCAL — aggregate-metrics (cli.py cron aggregate-metrics)
#   Daily 09:15 LOCAL — skill-maintain    (75)
#   Weekly Sun 09:30  — refine            (76)
#   Weekly Wed 10:00  — compact           (77)
# All run idempotently (empty inbox / nothing-to-do = clean no-op). Each 7x body
# self-logs to ~/.cache/nervepack/<job>.log. Re-running REPLACES each task (schtasks
# /F overwrite), never duplicates.
set -euo pipefail

# Test/override seams (see tests/onboard/test_install_memory_schtasks.sh):
SETUP_DIR="${NP_SCHTASKS_SETUP_DIR:-$HOME/Code/nervepack/engine/setup}"

# This is the native-Windows path; refuse elsewhere (NP_SCHTASKS_FORCE bypasses for
# tests). Git-for-Windows / MSYS2 / Cygwin bash report a MINGW*/MSYS*/CYGWIN* kernel.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) : ;;
  *) if [[ -z "${NP_SCHTASKS_FORCE:-}" ]]; then
       echo "70-install-memory-schtasks.sh is the native-Windows path — on Linux use 70-install-memory-cron.sh, on macOS use 70-install-memory-launchd.sh" >&2
       exit 1
     fi ;;
esac

# schtasks.exe is the scheduler; absent under NP_SCHTASKS_FORCE on non-Windows, so
# guard each call (the stub provides it in the test).
have_schtasks() { command -v schtasks >/dev/null 2>&1; }

# Windows path to bash.exe so the scheduled task can run the unix-path .sh body.
# cygpath is absent off-Windows (forced test runs) — fall back to the bare command.
BASH_WIN="$(cygpath -w "$(command -v bash)" 2>/dev/null || command -v bash)"

install_job() {  # $1=suffix  $2=schedule(DAILY|WEEKLY)  $3=weekday(- for daily)  $4=HH:MM
                  # $5=script-basename OR a full command (e.g. a "python3 .../cli.py cron
                  # <name>" dispatch, for jobs already ported off their bash original —
                  # see aggregate-metrics's call site below)
  local suffix="$1" sc="$2" day="$3" time="$4" script="$5"
  local tn="nervepack\\$suffix"
  local exec_cmd
  case "$script" in
    *.sh) exec_cmd="exec '$SETUP_DIR/$script'" ;;  # bare .sh basename — join with setup dir
    *) exec_cmd="exec $script" ;;                   # already a full command
  esac
  # Task action: launch Git-bash and exec the .sh body (bash resolves the unix path).
  local tr="\"$BASH_WIN\" -lc \"$exec_cmd\""
  if have_schtasks; then
    if [[ "$sc" == WEEKLY ]]; then
      schtasks //Create //TN "$tn" //TR "$tr" //SC WEEKLY //D "$day" //ST "$time" //F >/dev/null
    else
      schtasks //Create //TN "$tn" //TR "$tr" //SC DAILY //ST "$time" //F >/dev/null
    fi
  fi
  echo "Installed scheduled task: $tn ($sc${day:+ $day} $time -> $script)"
}

install_job memory-promote    DAILY  -   08:00 71-run-memory-promote.sh
install_job episodic-maintain DAILY  -   08:30 72-run-episodic-maintain.sh
install_job aggregate-metrics DAILY  -   09:00 "python3 $(dirname "$SETUP_DIR")/nervepack_engine/cli.py cron aggregate-metrics"
install_job skill-maintain    DAILY  -   09:15 75-skill-maintain.sh
install_job refine            WEEKLY SUN 09:30 76-run-refine.sh
install_job compact           WEEKLY WED 10:00 77-run-compact.sh

echo
echo "Requires: Git for Windows (provides the bash that runs the 7x job bodies)."
echo "Logs:   ~/.cache/nervepack/{memory-promote,episodic-maintain,aggregate-metrics,skill-maintain,refine,compact}.log"
echo "Verify: schtasks //Query //FO LIST | grep -i nervepack"
echo "Remove: for j in memory-promote episodic-maintain aggregate-metrics skill-maintain refine compact; do schtasks //Delete //TN \"nervepack\\\$j\" //F; done"
