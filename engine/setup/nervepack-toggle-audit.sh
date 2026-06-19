#!/usr/bin/env bash
# Report Nervepack hooks/cron scripts not represented (by family) in toggles.conf.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP_TOGGLES_CONF="${NP_TOGGLES_CONF:-$HERE/toggles.conf}"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
command -v jq >/dev/null || exit 0
mapfile -t fams < <(awk -F'|' '!/^[[:space:]]*#/ && NF>=4 {gsub(/^ +| +$/,"",$1); print $1}' "$NP_TOGGLES_CONF")
# known Nervepack scripts -> toggle family (extend as features are added)
declare -A MAP=(
  [nervepack-session-directive.sh]=directive [40-sync-nervepack.sh]=sync
  [episodic-capture.sh]=memory [episodic-recall.sh]=memory
  [71-run-memory-promote.sh]=memory [72-run-episodic-maintain.sh]=memory
  [playbook-guard.sh]=playbooks [playbook-recall.sh]=playbooks
  [np-evaluator.sh]=evaluator [73-aggregate-metrics.sh]=evaluator
)
in_conf() { local f="$1"; for x in "${fams[@]}"; do [[ "$x" == "$f" ]] && return 0; done; return 1; }

cmds="$( { [[ -f "$SETTINGS" ]] && jq -r '.. | objects | .command? // empty' "$SETTINGS"; crontab -l 2>/dev/null; } )"
flagged=0
while IFS= read -r line; do
  [[ "$line" == *nervepack* ]] || continue          # only Nervepack-owned commands
  s="$(echo "$line" | grep -oE '[a-zA-Z0-9_-]+\.sh' | head -1)"
  [[ -z "$s" ]] && continue
  # ignore installers/utilities that aren't toggleable features
  case "$s" in 30-link-skills.sh|60-generate-index.sh|*install*|nervepack-toggle*) continue ;; esac
  fam="${MAP[$s]:-}"
  if [[ -z "$fam" ]] || ! in_conf "$fam"; then echo "UNMANAGED: $s (no toggle family in toggles.conf)"; flagged=1; fi
done <<< "$cmds"
[[ "$flagged" == 0 ]] && echo "OK: all Nervepack hooks/cron map to a toggle family."
