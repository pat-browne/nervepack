#!/usr/bin/env bash
# nervepack-toggle: status | <feature> [on|off] | param <key> <value> | audit | (no args = interactive)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
NP_TOGGLES_CONF="${NP_TOGGLES_CONF:-$HERE/toggles.conf}"
NP_TOGGLES_LOCAL="${NP_TOGGLES_LOCAL:-$HOME/.config/nervepack/toggles.local}"
source "$HERE/np-toggle-lib.sh"

_scope() { awk -F'|' -v f="$1" '!/^[[:space:]]*#/ && $1==f{gsub(/^ +| +$/,"",$2);print $2;exit}' "$NP_TOGGLES_CONF"; }
_features() { awk -F'|' '!/^[[:space:]]*#/ && NF>=4 {gsub(/^ +| +$/,"",$1); print $1}' "$NP_TOGGLES_CONF"; }
_is_declared() {  # feature-name
  local f="$1" x
  while IFS= read -r x; do [[ "$x" == "$f" ]] && return 0; done < <(_features)
  return 1
}

_set_local() {  # key value
  mkdir -p "$(dirname "$NP_TOGGLES_LOCAL")"; touch "$NP_TOGGLES_LOCAL"
  grep -vE "^[[:space:]]*$1[[:space:]]*=" "$NP_TOGGLES_LOCAL" > "$NP_TOGGLES_LOCAL.tmp" 2>/dev/null || true
  echo "$1=$2" >> "$NP_TOGGLES_LOCAL.tmp"; mv "$NP_TOGGLES_LOCAL.tmp" "$NP_TOGGLES_LOCAL"
}
_set_conf_state() {  # feature state
  awk -F'|' -v f="$1" -v s="$2" 'BEGIN{OFS="|"} /^[[:space:]]*#/{print;next} $1==f{$4=s} {print}' "$NP_TOGGLES_CONF" > "$NP_TOGGLES_CONF.tmp" && mv "$NP_TOGGLES_CONF.tmp" "$NP_TOGGLES_CONF"
}
_set_conf_param() {  # feature.key value
  local feat="${1%%.*}" key="${1#*.}" val="$2"
  awk -F'|' -v f="$feat" -v k="$key" -v v="$val" 'BEGIN{OFS="|"} /^[[:space:]]*#/{print;next}
    $1==f{ p=$5; out=""; found=0; n=split(p,a,/[ ,]+/);
      for(i=1;i<=n;i++){ if(a[i]==""){continue}; split(a[i],kv,"="); if(kv[1]==k){a[i]=k"="v; found=1}; out=(out==""?a[i]:out" "a[i]) }
      if(!found){ out=(out==""?k"="v:out" "k"="v) } $5=out } {print}' "$NP_TOGGLES_CONF" > "$NP_TOGGLES_CONF.tmp" && mv "$NP_TOGGLES_CONF.tmp" "$NP_TOGGLES_CONF"
}
_commit_shared() {  # message
  [[ "${NP_TOGGLE_NO_COMMIT:-0}" == "1" ]] && return 0
  git -C "$NP" add "$NP_TOGGLES_CONF" >/dev/null 2>&1
  git -C "$NP" commit -q -m "$1" >/dev/null 2>&1 && git -C "$NP" push -q origin HEAD:main >/dev/null 2>&1 || true
}
_managed() {  # feature on|off
  [[ "${NP_TOGGLE_NO_MANAGED:-0}" == "1" ]] && { _set_local "$1" "$2"; return 0; }
  if [[ "$2" == "on" ]]; then "$HERE/90-install-claude-permissions.sh" >/dev/null 2>&1 || true
  else "$HERE/91-remove-claude-permissions.sh" >/dev/null 2>&1 || true; fi
  _set_local "$1" "$2"
}

flip() {  # feature on|off
  local feat="$1" state="$2" fam scope
  if _is_declared "$feat"; then fam="$feat"; else fam="${feat%%.*}"; fi
  scope="$(_scope "$fam")"
  case "$scope" in
    managed) _managed "$feat" "$state" ;;
    local)   _set_local "$feat" "$state" ;;
    shared|"")
      if [[ "$feat" != "$fam" ]]; then _set_local "$feat" "$state"
      else _set_conf_state "$feat" "$state"; _commit_shared "toggle($feat): $state"; fi ;;
  esac
  echo "$feat -> $state"
}

cmd="${1:-}"
case "$cmd" in
  ""|menu)   exec "$HERE/nervepack-toggle-menu.sh" ;;
  status)
    printf '%-14s %-7s %s\n' FEATURE STATE SCOPE
    while read -r f; do np_enabled "$f" && s=on || s=off; printf '%-14s %-7s %s\n' "$f" "$s" "$(_scope "$f")"; done < <(_features) ;;
  param)
    feat="${2%%.*}"; sc="$(_scope "$feat")"
    if [[ "$sc" == "shared" ]]; then _set_conf_param "$2" "$3"; _commit_shared "toggle($2): $3"; else _set_local "$2" "$3"; fi
    echo "$2 = $3" ;;
  audit)     exec "$HERE/nervepack-toggle-audit.sh" ;;
  *)
    feat="$cmd"; state="${2:-}"
    if [[ -z "$state" ]]; then np_enabled "$feat" && echo "$feat: on" || echo "$feat: off"; exit 0; fi
    [[ "$state" == "on" || "$state" == "off" ]] || { echo "usage: nervepack-toggle <feature> on|off" >&2; exit 2; }
    flip "$feat" "$state" ;;
esac
