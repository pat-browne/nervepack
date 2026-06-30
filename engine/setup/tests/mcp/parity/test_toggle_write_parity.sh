#!/usr/bin/env bash
# A/B parity for the toggle WRITE + STATUS surface ported to np_toggle.py:
#   - status table byte-identical to nervepack-toggle.sh status
#   - local-file writes (set-local) byte-identical to _set_local across new keys,
#     overwrites, dotted params, and preserving other keys.
# Shared-feature writes (conf + git commit/push) and managed scripts are NOT
# ported, so they're not compared here.
#
# Requires bash, so it runs on Linux + the Git-bash Windows lane, not the bash-free lane.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/nervepack-toggle.sh"
PY="$SETUP/np_toggle.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_toggle_write_parity: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0

cat > "$tmp/conf" <<'C'
# nervepack toggles (test fixture)
memory|shared|runtime|on|
playbooks|shared|runtime|off|
allowlist|local|managed|on|
mylocal|local|runtime|on|
sync|shared|runtime|on|interval=86400
C
export NP_TOGGLES_CONF="$tmp/conf"

# --- status table parity (several local-override states) --------------------
cmp_status() {  # $1=label (local file already written)
  export NP_TOGGLES_LOCAL="$tmp/status.local"
  diff <(bash "$SH" status 2>/dev/null) <(python3 "$PY" status 2>/dev/null) >/dev/null \
    && return 0
  echo "FAIL status [$1]:"; diff <(bash "$SH" status 2>/dev/null) <(python3 "$PY" status 2>/dev/null)
  fails=$((fails+1))
}
: > "$tmp/status.local";                         cmp_status "empty local"
printf 'memory=off\n'           > "$tmp/status.local"; cmp_status "memory off"
printf 'memory=off\nplaybooks=on\n' > "$tmp/status.local"; cmp_status "two overrides"

# --- set-local write parity (same sequence -> identical local files) --------
: > "$tmp/bash.local"; : > "$tmp/py.local"
apply() {  # $1=key $2=value  (feature uses on/off; dotted=param)
  if [[ "$1" == *.* ]]; then
    NP_TOGGLES_LOCAL="$tmp/bash.local" NP_TOGGLE_NO_COMMIT=1 NP_TOGGLE_NO_MANAGED=1 \
      bash "$SH" param "$1" "$2" >/dev/null 2>&1
  else
    NP_TOGGLES_LOCAL="$tmp/bash.local" NP_TOGGLE_NO_COMMIT=1 NP_TOGGLE_NO_MANAGED=1 \
      bash "$SH" "$1" "$2" >/dev/null 2>&1
  fi
  NP_TOGGLES_LOCAL="$tmp/py.local" python3 "$PY" set-local "$1" "$2"
  if ! cmp -s "$tmp/bash.local" "$tmp/py.local"; then
    echo "FAIL set-local after '$1=$2': bash=[$(tr '\n' ';' < "$tmp/bash.local")] python=[$(tr '\n' ';' < "$tmp/py.local")]"
    fails=$((fails+1))
  fi
}
apply allowlist off          # new key (local feature)
apply mylocal on             # second local feature
apply allowlist on           # overwrite first key, mylocal preserved
apply allowlist.opt_x v1     # dotted param under a local family (new)
apply allowlist.opt_x v2     # overwrite the param
apply mylocal off            # overwrite second feature, params preserved

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_toggle_write_parity: $fails mismatch(es)"
  exit 1
fi
echo "PASS test_toggle_write_parity"
