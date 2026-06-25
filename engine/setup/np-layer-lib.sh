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

# np_content_layers -> overlay roots, highest precedence first (team then personal).
# Team is included only when the `team` toggle is on AND np_team_dir resolves.
# Dedup so team==personal collapses to one line.
np_content_layers() {
  local personal team
  personal="$(np_content_dir 2>/dev/null)" || return 0
  if declare -f np_enabled >/dev/null 2>&1 && np_enabled team 2>/dev/null; then
    team="$(np_team_dir 2>/dev/null || true)"
  fi
  if [[ -n "${team:-}" && "$team" != "$personal" ]]; then
    printf '%s\n%s\n' "$team" "$personal"
  else
    printf '%s\n' "$personal"
  fi
}

# np_merge_mode -> validated team.merge value (override|concatenate|team-only).
np_merge_mode() {
  local m="override"
  declare -f np_param >/dev/null 2>&1 && m="$(np_param team.merge override 2>/dev/null || echo override)"
  case "$m" in override|concatenate|team-only) printf '%s\n' "$m" ;; *) printf 'override\n' ;; esac
}

# np_merge_roots -> the roots a reader should scan for the current mode.
# team-only + a configured team -> just the team (first) root; otherwise all layers.
# (team-only with NO team configured has only the personal root, so it falls through
# to "all layers" = personal-only — intended fail-open.)
np_merge_roots() {
  local mode i
  mode="$(np_merge_mode)"
  local roots=(); while IFS= read -r d; do [[ -n "$d" ]] && roots+=("$d"); done < <(np_content_layers)
  if [[ "$mode" == team-only && ${#roots[@]} -gt 1 ]]; then
    printf '%s\n' "${roots[0]}"
  else
    for ((i = 0; i < ${#roots[@]}; i++)); do printf '%s\n' "${roots[$i]}"; done
  fi
}
