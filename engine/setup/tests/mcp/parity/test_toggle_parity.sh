#!/usr/bin/env bash
# A/B parity: np_toggle.py (the Python port) must produce a byte-identical
# decision + exit code to np-toggle-lib.sh (the bash original) across an input
# table covering the known footguns — empty config, missing key, sub-toggle
# inheritance, local override, last-wins, value-with-spaces/equals, CRLF files,
# and comma/space-separated conf params.
#
# This is the regression that locks the two implementations together: change the
# bash toggle logic and this goes red until the Python matches (and vice-versa).
# Requires bash (it compares *against* bash), so it runs on Linux + the Git-bash
# Windows lane — not the bash-free lane (which runs the Python tests only).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
LIB="$SETUP/np-toggle-lib.sh"
PY="$SETUP/np_toggle.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_toggle_parity: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0

# Compare np_enabled: bash and python must agree on exit code (0=on,1=off).
cmp_enabled() {  # $1=feature
  local f="$1" bx px
  ( source "$LIB"; np_enabled "$f" ) >/dev/null 2>&1; bx=$?
  python3 "$PY" enabled "$f" >/dev/null 2>&1; px=$?
  if [[ "$bx" != "$px" ]]; then
    echo "FAIL enabled '$f': bash exit=$bx python exit=$px (conf=${NP_TOGGLES_CONF:-} local=${NP_TOGGLES_LOCAL:-})"
    fails=$((fails+1))
  fi
}

# Compare np_param: byte-identical stdout (captured to files, cmp'd).
cmp_param() {  # $1=key $2=default
  local k="$1" d="$2"
  ( source "$LIB"; np_param "$k" "$d" ) > "$tmp/b.out" 2>/dev/null
  python3 "$PY" param "$k" "$d" > "$tmp/p.out" 2>/dev/null
  if ! cmp -s "$tmp/b.out" "$tmp/p.out"; then
    echo "FAIL param '$k' (def '$d'): bash=[$(cat "$tmp/b.out")] python=[$(cat "$tmp/p.out")] (conf=${NP_TOGGLES_CONF:-} local=${NP_TOGGLES_LOCAL:-})"
    fails=$((fails+1))
  fi
}

# --- Case A: both files absent (pure defaults / fail-open) ------------------
export NP_TOGGLES_CONF="$tmp/none.conf" NP_TOGGLES_LOCAL="$tmp/none.local"
cmp_enabled memory
cmp_enabled memory.recall
cmp_param sync.interval 999
cmp_param plain 42

# --- Case B: conf present, no local -----------------------------------------
cat > "$tmp/b.conf" <<'C'
# a comment line
memory|shared|runtime|on|
playbooks|shared|runtime|off|
sync|shared|runtime|on|interval=86400
evaluator|shared|runtime|on|cap_bytes=1000, dashboard_serve=on
allowlist|local|managed|on|
C
export NP_TOGGLES_CONF="$tmp/b.conf" NP_TOGGLES_LOCAL="$tmp/none.local"
cmp_enabled memory
cmp_enabled playbooks
cmp_enabled memory.capture           # sub inherits family on
cmp_enabled playbooks.foo            # sub inherits family off
cmp_enabled missingfeature           # unknown -> fail-open on
cmp_param sync.interval 999          # conf param
cmp_param evaluator.cap_bytes 0      # comma-separated conf param
cmp_param evaluator.dashboard_serve off
cmp_param evaluator.missing 7        # param not in conf -> default
cmp_param no.such 42

# --- Case C: local overrides ------------------------------------------------
cat > "$tmp/c.local" <<'C'
memory=off
memory.recall=on
sync.interval=3600
C
export NP_TOGGLES_CONF="$tmp/b.conf" NP_TOGGLES_LOCAL="$tmp/c.local"
cmp_enabled memory                   # local override off
cmp_enabled memory.capture           # sub inherits local family off
cmp_enabled memory.recall            # explicit sub override on
cmp_param sync.interval 999          # local param override

# --- Case D: CRLF config files ----------------------------------------------
printf 'memory|shared|runtime|on|\r\nsync|shared|runtime|on|interval=86400\r\n' > "$tmp/d.conf"
printf 'memory=off\r\nsync.interval=3600\r\n' > "$tmp/d.local"
export NP_TOGGLES_CONF="$tmp/d.conf" NP_TOGGLES_LOCAL="$tmp/d.local"
cmp_enabled memory
cmp_enabled sync
cmp_param sync.interval 999

# --- Case E: last-wins duplicate local key ----------------------------------
printf 'foo=first\nfoo=second\n' > "$tmp/e.local"
export NP_TOGGLES_CONF="$tmp/none.conf" NP_TOGGLES_LOCAL="$tmp/e.local"
cmp_param foo X

# --- Case F: value with spaces and embedded equals --------------------------
printf 'greeting = hello world\nexpr=a=b=c\n' > "$tmp/f.local"
export NP_TOGGLES_CONF="$tmp/none.conf" NP_TOGGLES_LOCAL="$tmp/f.local"
cmp_param greeting X
cmp_param expr X

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_toggle_parity: $fails parity mismatch(es)"
  exit 1
fi
echo "PASS test_toggle_parity"
