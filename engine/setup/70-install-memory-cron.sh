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

install_line "nervepack-memory-promote" \
  "0 8 * * * $HOME/Code/nervepack/engine/setup/71-run-memory-promote.sh # nervepack-memory-promote"
install_line "nervepack-episodic-maintain" \
  "30 8 * * * $HOME/Code/nervepack/engine/setup/72-run-episodic-maintain.sh # nervepack-episodic-maintain"
install_line "nervepack-aggregate-metrics" \
  "0 9 * * * $HOME/Code/nervepack/engine/setup/73-aggregate-metrics.sh # nervepack-aggregate-metrics"
install_line "nervepack-skill-maintain" \
  "15 9 * * * $HOME/Code/nervepack/engine/setup/75-skill-maintain.sh # nervepack-skill-maintain"

echo
echo "Logs: ~/.cache/nervepack/memory-promote.log, ~/.cache/nervepack/episodic-maintain.log, ~/.cache/nervepack/skill-maintain.log"
echo "Verify: crontab -l | grep nervepack-"
echo "Remove: crontab -l | grep -vF 'nervepack-memory-promote' | grep -vF 'nervepack-episodic-maintain' | grep -vF 'nervepack-aggregate-metrics' | grep -vF 'nervepack-skill-maintain' | crontab -"
