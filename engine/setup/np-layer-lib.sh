#!/usr/bin/env bash
# nervepack layer resolver. SOURCE this; do not execute.
# Builds on np-content-lib.sh (np_content_dir / np_team_dir) + np-toggle-lib.sh
# (np_enabled / np_param) to expose the team>personal overlay stack and the
# user-selected `team.merge` mode to the readers.
_npll_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$_npll_dir/np-content-lib.sh"
# np-toggle-lib provides np_enabled / np_param; load best-effort (fail-open).
[[ -r "$_npll_dir/np-toggle-lib.sh" ]] && source "$_npll_dir/np-toggle-lib.sh"

# np_content_layers -> overlay roots, highest precedence first: all configured team
# dirs (in precedence order) then personal. Team roots included only when the `team`
# toggle is on. Dedup so a team root equal to personal collapses.
np_content_layers() {
  local personal
  personal="$(np_content_dir 2>/dev/null)" || return 0
  local layers=()
  if declare -f np_enabled >/dev/null 2>&1 && np_enabled team 2>/dev/null; then
    local t e dup
    while IFS= read -r t; do
      [[ -n "$t" && "$t" != "$personal" ]] || continue
      dup=0
      for e in "${layers[@]:-}"; do [[ "$e" == "$t" ]] && { dup=1; break; }; done
      [[ "$dup" == 1 ]] || layers+=("$t")
    done < <(np_team_dirs 2>/dev/null || true)
  fi
  layers+=("$personal")
  printf '%s\n' "${layers[@]}"
}

# np_merge_mode -> validated team.merge value (override|concatenate|team-only).
np_merge_mode() {
  local m="override"
  declare -f np_param >/dev/null 2>&1 && m="$(np_param team.merge override 2>/dev/null || echo override)"
  case "$m" in override|concatenate|team-only) printf '%s\n' "$m" ;; *) printf 'override\n' ;; esac
}

# np_merge_roots -> the roots a reader should scan for the current mode.
# team-only + >=1 configured team -> all team roots (personal dropped); otherwise
# all layers. (team-only with NO team configured has only the personal root, so it
# falls through to "all layers" = personal-only — intended fail-open.)
np_merge_roots() {
  local mode i
  mode="$(np_merge_mode)"
  local roots=(); while IFS= read -r d; do [[ -n "$d" ]] && roots+=("$d"); done < <(np_content_layers)
  if [[ "$mode" == team-only && ${#roots[@]} -gt 1 ]]; then
    # all team roots = every layer except the personal (last) one
    for ((i = 0; i < ${#roots[@]} - 1; i++)); do printf '%s\n' "${roots[$i]}"; done
  else
    for ((i = 0; i < ${#roots[@]}; i++)); do printf '%s\n' "${roots[$i]}"; done
  fi
}

# np_layer_roots <layer> -> one line per merge root, each suffixed memory/<layer>.
# The merge-aware sibling of np_layer_dir: recall hooks scan these for the active
# team.merge mode. Keeps the memory/ subpath defined in exactly one conceptual place
# (mirrors np_layer_dir; both append memory/<layer>).
np_layer_roots() {
  local layer="$1" r
  while IFS= read -r r; do
    [[ -n "$r" ]] && printf '%s/memory/%s\n' "$r" "$layer"
  done < <(np_merge_roots)
}
