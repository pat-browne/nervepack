#!/usr/bin/env bash
# Idempotently install the nervepack cron entries:
#   Daily 08:00 LOCAL — memory-promote (memory→nervepack promotion)
#   Daily 08:30 LOCAL — episodic-maintain (episodic-memory maintenance pass)
#   Daily 09:00 LOCAL — aggregate-metrics (drain evaluator inbox → metrics.jsonl)
# All run daily and are idempotent — an empty inbox / nothing-to-do is a clean no-op
# (no commit), so daily cadence just shortens the latency to a committed layer.
set -euo pipefail

if ! command -v crontab >/dev/null; then
  echo "crontab not available — install cron (sudo apt install -y cron) and retry" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-toggle-lib.sh"

install_line() {  # $1=marker  $2=full crontab line
  local marker="$1" line="$2"
  local existing filtered
  existing="$(crontab -l 2>/dev/null || true)"
  # Remove any existing line containing the marker, then add the new one.
  # This ensures a path change REPLACES the stale entry rather than duplicating it.
  filtered="$(printf '%s\n' "$existing" | grep -vF "$marker" | grep -v '^$' || true)"
  printf '%s\n%s\n' "$filtered" "$line" | grep -v '^$' | crontab -
  echo "Installed cron entry: $line"
}

remove_line() {  # $1=marker — drop any crontab line containing marker; no-op if absent
  local marker="$1" existing filtered
  existing="$(crontab -l 2>/dev/null || true)"
  printf '%s\n' "$existing" | grep -qF "$marker" || return 0
  filtered="$(printf '%s\n' "$existing" | grep -vF "$marker" | grep -v '^$' || true)"
  printf '%s\n' "$filtered" | grep -v '^$' | crontab -
  echo "Removed cron entry matching: $marker"
}

install_line "nervepack-memory-promote" \
  "0 8 * * * $HOME/Code/nervepack/engine/setup/71-run-memory-promote.sh # nervepack-memory-promote"
install_line "nervepack-episodic-maintain" \
  "30 8 * * * $HOME/Code/nervepack/engine/setup/72-run-episodic-maintain.sh # nervepack-episodic-maintain"
install_line "nervepack-aggregate-metrics" \
  "0 9 * * * $HOME/Code/nervepack/engine/setup/73-aggregate-metrics.sh # nervepack-aggregate-metrics"
install_line "nervepack-skill-maintain" \
  "15 9 * * * $HOME/Code/nervepack/engine/setup/75-skill-maintain.sh # nervepack-skill-maintain"
install_line "nervepack-refine" \
  "30 9 * * 0 $HOME/Code/nervepack/engine/setup/76-run-refine.sh # nervepack-refine"
install_line "nervepack-compact" \
  "0 10 * * 3 $HOME/Code/nervepack/engine/setup/77-run-compact.sh # nervepack-compact"

# --- Opt-in resume-pointer interval cron (default off; toggle: resume.cron) ---
# When on, runs the writer for the ACTIVE session (--active discovery, since cron
# has no stdin/hook payload to supply --session/--transcript/--cwd) every
# resume.cron_min minutes, composed with --throttle so it defers to resume.interval.
# When off (default), any previously-installed entry is removed so a flip back to
# off cleans up rather than leaving a stale line.
RESUME_MARKER="nervepack-resume-cron"
if [[ "$(np_param resume.cron off)" == "on" ]]; then
  cron_min="$(np_param resume.cron_min 5)"
  [[ "$cron_min" =~ ^[0-9]+$ ]] || cron_min=5
  install_line "$RESUME_MARKER" \
    "*/$cron_min * * * * $HOME/Code/nervepack/engine/setup/np-resume-write.sh --active --throttle # $RESUME_MARKER"
else
  remove_line "$RESUME_MARKER"
fi

echo
echo "Logs: ~/.cache/nervepack/memory-promote.log, ~/.cache/nervepack/episodic-maintain.log, ~/.cache/nervepack/skill-maintain.log, ~/.cache/nervepack/refine.log, ~/.cache/nervepack/compact.log"
echo "Verify: crontab -l | grep nervepack-"
echo "Remove: crontab -l | grep -vF 'nervepack-memory-promote' | grep -vF 'nervepack-episodic-maintain' | grep -vF 'nervepack-aggregate-metrics' | grep -vF 'nervepack-skill-maintain' | grep -vF 'nervepack-refine' | grep -vF 'nervepack-compact' | crontab -"
