#!/usr/bin/env bash
# macOS launchd equivalent of 70-install-memory-cron.sh. Installs the nervepack
# maintenance jobs as per-user LaunchAgents (cron isn't the native scheduler on
# macOS; user crontab works but launchd is the supported path and survives reboots
# cleanly):
#   Daily 08:00 LOCAL — memory-promote      (cli.py cron memory-promote)
#   Daily 08:30 LOCAL — episodic-maintain   (cli.py cron episodic-maintain)
#   Daily 09:00 LOCAL — aggregate-metrics   (cli.py cron aggregate-metrics)
#   Daily 09:15 LOCAL — skill-maintain      (cli.py cron skill-maintain)
# All run daily and are idempotent (empty inbox / nothing-to-do = clean no-op), so
# the cadence just shortens latency to a committed layer. Re-running this installer
# REPLACES each agent (rewrite plist + reload), never duplicates.
set -euo pipefail

# Test/override seams (see tests/onboard/test_install_memory_launchd.sh):
LA_DIR="${NP_LAUNCHAGENTS_DIR:-$HOME/Library/LaunchAgents}"
LOG_DIR="${NP_LAUNCHD_LOG_DIR:-$HOME/.cache/nervepack}"
SETUP_DIR="${NP_LAUNCHD_SETUP_DIR:-$HOME/Code/nervepack/engine/setup}"

# This is the macOS path; refuse on other OSes (NP_LAUNCHD_FORCE bypasses for tests).
if [[ "$(uname -s)" != Darwin && -z "${NP_LAUNCHD_FORCE:-}" ]]; then
  echo "70-install-memory-launchd.sh is the macOS path — on Linux use 70-install-memory-cron.sh" >&2
  exit 1
fi

mkdir -p "$LA_DIR" "$LOG_DIR"

# launchctl is the loader; absent under NP_LAUNCHD_FORCE on non-mac, so guard each call.
have_launchctl() { command -v launchctl >/dev/null 2>&1; }

install_job() {  # $1=job-suffix  $2=hour  $3=minute  $4=script-basename OR a full command
                  # (e.g. a "python3 .../cli.py cron <name>" dispatch, for jobs already
                  # ported off their bash original — see aggregate-metrics's call site below)
  local suffix="$1" hour="$2" minute="$3" script="$4"
  local label="com.nervepack.$suffix"
  local plist="$LA_DIR/$label.plist"
  local log="$LOG_DIR/$suffix.log"
  local exec_cmd
  case "$script" in
    *.sh) exec_cmd="exec \"$SETUP_DIR/$script\"" ;;  # bare .sh basename — join with setup dir
    *) exec_cmd="exec $script" ;;                     # already a full command
  esac
  # `/bin/bash -lc` gives the job a login-shell PATH (launchd's env is otherwise
  # minimal — git/jq/claude/node would be missing, exactly as with cron).
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>$exec_cmd</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$hour</integer>
    <key>Minute</key><integer>$minute</integer>
  </dict>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
PLIST
  if have_launchctl; then
    # unload-then-load is the version-portable idempotent reload (older + newer macOS).
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load -w "$plist"
  fi
  echo "Installed launchd agent: $label ($hour:$minute -> $script)"
}

install_job memory-promote    8  0 "python3 $(dirname "$SETUP_DIR")/nervepack_engine/cli.py cron memory-promote"
install_job episodic-maintain 8 30 "python3 $(dirname "$SETUP_DIR")/nervepack_engine/cli.py cron episodic-maintain"
install_job aggregate-metrics 9  0 "python3 $(dirname "$SETUP_DIR")/nervepack_engine/cli.py cron aggregate-metrics"
install_job skill-maintain    9 15 "python3 $(dirname "$SETUP_DIR")/nervepack_engine/cli.py cron skill-maintain"
install_job refine            9 30 "python3 $(dirname "$SETUP_DIR")/nervepack_engine/cli.py cron refine"
install_job compact          10  0 77-run-compact.sh

echo
echo "Logs:   $LOG_DIR/{memory-promote,episodic-maintain,aggregate-metrics,skill-maintain,refine,compact}.log"
echo "Verify: launchctl list | grep com.nervepack"
echo "Remove: for j in memory-promote episodic-maintain aggregate-metrics skill-maintain refine compact; do launchctl unload \"$LA_DIR/com.nervepack.\$j.plist\" 2>/dev/null; rm -f \"$LA_DIR/com.nervepack.\$j.plist\"; done"
