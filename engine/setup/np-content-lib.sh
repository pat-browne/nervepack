#!/usr/bin/env bash
# nervepack content-dir resolver. SOURCE this; do not execute.
#
# np_content_dir -> prints the content overlay root (where the user's skills/
# episodic/playbooks/strategies/sources/wiki + dashboard metrics live).
# Resolution order:
#   1. $NP_CONTENT_DIR (env)
#   2. ~/.config/nervepack/content-dir (first line)
#   3. default: the engine repo root (this file's ../../) -> byte-identical to legacy behavior
# An explicit (env/config) path that doesn't exist is a hard error (return 1, loud);
# an UNSET config falls through to the default, which always exists.
_npc_setup="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_npc_engine="$(cd "$_npc_setup/../.." && pwd)"

np_content_dir() {
  local d=""
  if [[ -n "${NP_CONTENT_DIR:-}" ]]; then
    d="$NP_CONTENT_DIR"
  elif [[ -f "$HOME/.config/nervepack/content-dir" ]]; then
    d="$(head -n1 "$HOME/.config/nervepack/content-dir" 2>/dev/null)"
  fi
  d="${d:-$_npc_engine}"
  if [[ ! -d "$d" ]]; then
    echo "np-content: content dir not found: $d" >&2
    return 1
  fi
  printf '%s\n' "$d"
}

# np_content_dir_origin -> prints HOW np_content_dir resolved, the single source of truth
# for the explicit-vs-implicit distinction (issue #12). It mirrors np_content_dir's
# resolution order WITHOUT changing its stdout:
#   env     -> $NP_CONTENT_DIR was set (explicit)
#   config  -> ~/.config/nervepack/content-dir exists (explicit — even if it points at
#              the engine root, that is a DELIBERATE single-repo opt-in)
#   default -> neither set -> the silent engine-root fallback (implicit/accidental)
# Personal-content writers (71/72/73/75) and the doctor share this one detector so the
# detection is never scattered.
np_content_dir_origin() {
  if [[ -n "${NP_CONTENT_DIR:-}" ]]; then
    printf 'env\n'
  elif [[ -f "$HOME/.config/nervepack/content-dir" ]]; then
    printf 'config\n'
  else
    printf 'default\n'
  fi
}

# np_content_is_explicit -> return 0 when the content dir was chosen explicitly
# (env or config), non-zero when it came from the implicit engine-root fallback.
# Personal-content writers gate their commit on this: on the implicit fallback they
# SKIP the commit (fail-open) so they never pollute the PII-clean engine repo.
np_content_is_explicit() {
  [[ "$(np_content_dir_origin)" != default ]]
}

# np_team_dir -> prints the OPTIONAL team overlay root (a shared content layer that
# overrides the personal overlay). Resolution mirrors np_content_dir:
#   1. $NP_TEAM_DIR (env)   2. ~/.config/nervepack/team-dir (first line)   3. none
# Unconfigured -> print nothing, return non-zero (callers treat "no team" as normal).
# Explicit-but-missing -> loud error, return 1 (parity with np_content_dir).
np_team_dir() {
  local d=""
  if [[ -n "${NP_TEAM_DIR:-}" ]]; then
    d="$NP_TEAM_DIR"
  elif [[ -f "$HOME/.config/nervepack/team-dir" ]]; then
    d="$(head -n1 "$HOME/.config/nervepack/team-dir" 2>/dev/null)"
  fi
  [[ -n "$d" ]] || return 1
  if [[ ! -d "$d" ]]; then
    echo "np-content: team dir not found: $d" >&2
    return 1
  fi
  printf '%s\n' "$d"
}

# np_team_dir_origin -> how np_team_dir resolved: env | config | none.
np_team_dir_origin() {
  if [[ -n "${NP_TEAM_DIR:-}" ]]; then
    printf 'env\n'
  elif [[ -f "$HOME/.config/nervepack/team-dir" ]]; then
    printf 'config\n'
  else
    printf 'none\n'
  fi
}
