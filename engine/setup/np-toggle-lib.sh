#!/usr/bin/env bash
# Nervepack toggle resolver. SOURCE this; do not execute.
# np_enabled <feature>  -> exit 0 if on, 1 if off (fail-open: unknown = on)
# np_param   <key> <def> -> resolve a param value
_np_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP_TOGGLES_CONF="${NP_TOGGLES_CONF:-$_np_dir/toggles.conf}"
NP_TOGGLES_LOCAL="${NP_TOGGLES_LOCAL:-$HOME/.config/nervepack/toggles.local}"

_np_local_get() {  # $1=key -> prints value or nothing
  [[ -f "$NP_TOGGLES_LOCAL" ]] || return 0
  grep -E "^[[:space:]]*$1[[:space:]]*=" "$NP_TOGGLES_LOCAL" 2>/dev/null \
    | tail -1 | sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*$//'
}
_np_conf_state() {  # $1=feature -> prints state column
  [[ -f "$NP_TOGGLES_CONF" ]] || return 0
  awk -F'|' -v f="$1" '!/^[[:space:]]*#/ && $1==f {gsub(/^ +| +$/,"",$4); print $4; exit}' "$NP_TOGGLES_CONF"
}
_np_conf_param() {  # $1=feature.param -> prints param value
  local feat="${1%%.*}" p="${1#*.}"
  [[ -f "$NP_TOGGLES_CONF" ]] || return 0
  awk -F'|' -v f="$feat" -v p="$p" '!/^[[:space:]]*#/ && $1==f {
    n=split($5,a,/[ ,]+/); for(i=1;i<=n;i++){split(a[i],kv,"="); gsub(/^ +| +$/,"",kv[1]); if(kv[1]==p){print kv[2]; exit}}
  }' "$NP_TOGGLES_CONF"
}
np_enabled() {  # $1=feature
  local feat="$1" v
  v="$(_np_local_get "$feat")"
  if [[ -z "$v" && "$feat" == *.* ]]; then feat="${feat%%.*}"; v="$(_np_local_get "$feat")"; fi
  [[ -z "$v" ]] && v="$(_np_conf_state "$feat")"
  [[ -z "$v" ]] && v="on"
  [[ "$v" == "on" ]]
}
np_param() {  # $1=key $2=default
  local v; v="$(_np_local_get "$1")"
  [[ -z "$v" ]] && v="$(_np_conf_param "$1")"
  [[ -z "$v" ]] && v="$2"
  printf '%s' "$v"
}

np_signal() {  # $1=session_id $2=message — append a fire marker if evaluator.signals on
  np_enabled evaluator.signals || return 0
  local d="${NP_SIGNAL_DIR:-$HOME/.cache/nervepack/session-signals}"
  mkdir -p "$d" 2>/dev/null || return 0
  printf '%s\n' "$2" >> "$d/${1//\//_}.log" 2>/dev/null || true
}
