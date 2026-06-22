#!/usr/bin/env bash
# Interactive feature picker. Number toggles that feature; 's' saves & quits; 'q' quits.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP_TOGGLES_CONF="${NP_TOGGLES_CONF:-$HERE/toggles.conf}"
NP_TOGGLES_LOCAL="${NP_TOGGLES_LOCAL:-$HOME/.config/nervepack/toggles.local}"
source "$HERE/np-toggle-lib.sh"
# bash 3.2 (stock macOS) has no `mapfile` — read into the array with a loop.
FEATS=()
while IFS= read -r _f; do FEATS+=("$_f"); done < <(awk -F'|' '!/^[[:space:]]*#/ && NF>=4 {gsub(/^ +| +$/,"",$1); print $1}' "$NP_TOGGLES_CONF")

render() {
  echo "Nervepack feature toggles — number to flip, 's' save & quit, 'q' quit"
  local i=1 f b
  for f in "${FEATS[@]}"; do
    np_enabled "$f" && b="[x]" || b="[ ]"; printf "  %2d) %s %s\n" "$i" "$b" "$f"; ((i++))
  done
}
while true; do
  render
  read -r -p "> " choice || break
  case "$choice" in
    q|s) exit 0 ;;
    ''|*[!0-9]*) continue ;;
    *) idx=$((choice-1)); [[ $idx -ge 0 && $idx -lt ${#FEATS[@]} ]] || continue
       f="${FEATS[$idx]}"; np_enabled "$f" && ns=off || ns=on
       NP_TOGGLES_CONF="$NP_TOGGLES_CONF" NP_TOGGLES_LOCAL="$NP_TOGGLES_LOCAL" bash "$HERE/nervepack-toggle.sh" "$f" "$ns" >/dev/null ;;
  esac
done
