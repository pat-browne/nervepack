#!/usr/bin/env bash
# Regression for setup/74-open-dashboard.sh: the SessionStart open is gated by the
# evaluator.dashboard_open param (default on) and guarded to once per OS boot. Both
# gates short-circuit BEFORE the aggregate/open side effects, so this is a clean
# black-box test via the NP_* seams (opener, marker, aggregate, toggle files).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$HERE/../../74-open-dashboard.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# A stub opener that records the URL it was asked to open.
opened="$tmp/opened"
cat > "$tmp/opener" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$1" >> "$opened"
EOF
chmod +x "$tmp/opener"
boot="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown)"

# dashboard_serve=off keeps np_dashboard_url on the cheap file:// path (no server spawn).
cat > "$tmp/toggles.conf" <<'C'
evaluator|shared|runtime|on|dashboard_open=on,dashboard_serve=off,dashboard_port=8787
C

run() {  # $1=marker-seed ("" = fresh)
  rm -f "$tmp/marker"; [[ -n "$1" ]] && printf '%s' "$1" > "$tmp/marker"
  : > "$opened"
  NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
  NP_DASH_MARKER="$tmp/marker" NP_DASH_OPENER="$tmp/opener" NP_DASH_AGGREGATE=true \
    bash "$HOOK"
}

# 1. Enabled + fresh boot -> opens exactly once, writes the boot marker.
run ""
[[ -s "$opened" ]] || { echo "FAIL: expected open on fresh boot"; exit 1; }
[[ "$(cat "$tmp/marker")" == "$boot" ]] || { echo "FAIL: boot marker not written"; exit 1; }
# The file:// fallback URL must point at a real file — guards against a repo-root
# path derivation regressing (e.g. the engine/ split made it .../engine/dashboard/...).
url="$(cat "$opened")"; fpath="${url#file://}"
[[ "$url" == file://* && -f "$fpath" ]] || { echo "FAIL: file:// fallback points at a missing path: $url"; exit 1; }

# 2. Marker already matches this boot -> does NOT open again (the loop guard).
run "$boot"
[[ ! -s "$opened" ]] || { echo "FAIL: opened despite matching boot marker"; exit 1; }

# 3. dashboard_open=off -> does NOT open (the param gate).
printf 'evaluator.dashboard_open=off\n' > "$tmp/local"
run ""
[[ ! -s "$opened" ]] || { echo "FAIL: opened despite dashboard_open=off"; exit 1; }
rm -f "$tmp/local"

echo "PASS test_open_dashboard"
