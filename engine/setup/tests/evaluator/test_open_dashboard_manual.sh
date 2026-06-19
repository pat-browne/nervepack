#!/usr/bin/env bash
# np-test: open-dashboard | happy+failure
# open-dashboard.sh is the manual, on-demand open (no boot guard). It rebuilds the
# data file, resolves the URL via np_dashboard_url, then hands it to an opener
# (NP_DASH_OPENER overrides xdg-open for tests). Fail-open: never hard-errors.
#   HAPPY:   serve=off -> file:// URL is passed to the stub opener, which records
#            it; the script prints "opened <url>" and exits 0.
#   FAILURE: opener binary missing -> prints "no opener (...) found", opens
#            NOTHING, and STILL exits 0 (fail-open invariant).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPEN="$HERE/../../open-dashboard.sh"
NP="$(cd "$HERE/../../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# serve=off keeps np_dashboard_url on the cheap, deterministic file:// path.
cat > "$tmp/toggles.conf" <<'C'
evaluator|shared|runtime|on|dashboard_serve=off,dashboard_port=8787
C
expect="file://$NP/dashboard/index.html"

# --- HAPPY: stub opener records the URL it is asked to open ------------------
opened="$tmp/opened"
cat > "$tmp/opener" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$1" >> "$opened"
EOF
chmod +x "$tmp/opener"
: > "$opened"
rc=0; out="$(NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
  NP_DASH_OPENER="$tmp/opener" bash "$OPEN" 2>&1)" || rc=$?
[[ "$rc" == 0 ]] || { echo "FAIL(happy): exit $rc: $out"; exit 1; }
[[ "$(cat "$opened")" == "$expect" ]] \
  || { echo "FAIL(happy): opener got '$(cat "$opened")' (want $expect)"; exit 1; }
echo "$out" | grep -qF "opened $expect" \
  || { echo "FAIL(happy): missing 'opened <url>' line: $out"; exit 1; }

# --- FAILURE: opener binary missing -> graceful, exit 0, opens nothing -------
: > "$opened"
rc=0; out="$(NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
  NP_DASH_OPENER="$tmp/does-not-exist-opener" bash "$OPEN" 2>&1)" || rc=$?
[[ "$rc" == 0 ]] || { echo "FAIL(failure): missing opener gave non-zero exit $rc: $out"; exit 1; }
echo "$out" | grep -qi 'no opener' \
  || { echo "FAIL(failure): missing the 'no opener' diagnostic: $out"; exit 1; }
[[ ! -s "$opened" ]] || { echo "FAIL(failure): something was opened despite missing opener: $(cat "$opened")"; exit 1; }
echo "PASS test_open_dashboard_manual"
