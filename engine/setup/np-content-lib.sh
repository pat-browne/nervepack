#!/usr/bin/env bash
# nervepack content-dir resolver. SOURCE this; do not execute.
#
# np_content_dir -> prints the content overlay root (where the user's skills/
# episodic/lessons/sources/wiki + dashboard metrics live).
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

# np_team_dirs -> one line per configured team overlay, HIGHEST-PRECEDENCE FIRST.
# The value (NP_TEAM_DIR env, else ~/.config/nervepack/team-dir first line) is a
# comma-separated list; a single value is the 1-element case. Splits on ',', trims
# surrounding whitespace, drops empties, dedups (order-preserving). Validates:
#   - > 4 entries exceeds the 5-layer cap (team+personal) -> loud error, return 1;
#   - any entry that isn't a dir -> loud error, return 1.
# Unconfigured -> print nothing, return 1 ("no team" is normal). This is the single
# parse/validate point; np_team_dir and every consumer build on it.
np_team_dirs() {
  local raw=""
  if [[ -n "${NP_TEAM_DIR:-}" ]]; then
    raw="$NP_TEAM_DIR"
  elif [[ -f "$HOME/.config/nervepack/team-dir" ]]; then
    raw="$(head -n1 "$HOME/.config/nervepack/team-dir" 2>/dev/null)"
  fi
  [[ -n "$raw" ]] || return 1
  local dirs=() parts=() p d e dup
  IFS=',' read -ra parts <<< "$raw"
  for p in "${parts[@]}"; do
    d="${p#"${p%%[![:space:]]*}"}"   # ltrim
    d="${d%"${d##*[![:space:]]}"}"   # rtrim
    [[ -n "$d" ]] || continue
    dup=0
    for e in "${dirs[@]:-}"; do [[ "$e" == "$d" ]] && { dup=1; break; }; done
    [[ "$dup" == 1 ]] || dirs+=("$d")
  done
  [[ ${#dirs[@]} -gt 0 ]] || return 1
  if [[ ${#dirs[@]} -gt 4 ]]; then
    echo "np-content: team list exceeds cap (max 4 team dirs / 5 layers): $raw" >&2
    return 1
  fi
  for d in "${dirs[@]}"; do
    if [[ ! -d "$d" ]]; then
      echo "np-content: team dir not found: $d" >&2
      return 1
    fi
  done
  printf '%s\n' "${dirs[@]}"
}

# np_team_dir -> the HIGHEST-PRECEDENCE team dir (first line of np_team_dirs), for
# consumers that legitimately want just "the team". Single-line stdout contract
# unchanged. Loud errors from np_team_dirs pass through on stderr.
np_team_dir() {
  local out
  out="$(np_team_dirs)" || return 1
  printf '%s\n' "${out%%$'\n'*}"
}

# np_layer_dir <layer> -> the single-root path of an agent-owned memory layer,
# now grouped under memory/ (episodic|lessons). Single source of truth
# for the layer subpath: future relocations change ONLY this function. Used by
# single-root consumers (lesson-guard, 73, 75). Recall hooks use np_layer_roots
# (np-layer-lib.sh) for the team/personal merge.
np_layer_dir() {
  local layer="$1"
  printf '%s/memory/%s\n' "$(np_content_dir)" "$layer"
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
