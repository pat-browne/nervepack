#!/usr/bin/env bash
# np-test: resolve-opener | unit
# np_resolve_opener (in np-dashboard-launch.sh) picks the URL opener cross-platform:
#   - honors an explicit NP_DASH_OPENER override (tests/headless),
#   - else prefers xdg-open (Linux) when present,
#   - else falls back to open (macOS),
#   - else returns non-zero / empty (caller fail-opens).
# Regression: the default used to be hardcoded "xdg-open", so on macOS (no xdg-open)
# the dashboard never opened even though the server was up.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH="$HERE/../../np-dashboard-launch.sh"

# Source the launcher with a normal PATH (it shells out to dirname/cd at load).
# shellcheck source=/dev/null
source "$LAUNCH"
declare -F np_resolve_opener >/dev/null \
  || { echo "FAIL: np_resolve_opener not defined"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mk() { printf '#!/usr/bin/env bash\n:\n' > "$tmp/$1"; chmod +x "$tmp/$1"; }

# --- macOS-like: only `open` on PATH, no xdg-open -> resolves to open ----------
mk open
got="$(PATH="$tmp" NP_DASH_OPENER= np_resolve_opener || true)"
[[ "$got" == "open" ]] || { echo "FAIL(macos): got '$got' (want open)"; exit 1; }

# --- Linux-like: both present -> prefers xdg-open ------------------------------
mk xdg-open
got="$(PATH="$tmp" NP_DASH_OPENER= np_resolve_opener || true)"
[[ "$got" == "xdg-open" ]] || { echo "FAIL(linux): got '$got' (want xdg-open)"; exit 1; }

# --- explicit override wins regardless of PATH --------------------------------
got="$(PATH="$tmp" NP_DASH_OPENER=my-opener np_resolve_opener || true)"
[[ "$got" == "my-opener" ]] || { echo "FAIL(override): got '$got' (want my-opener)"; exit 1; }

# --- nothing available -> non-zero, empty output (caller fail-opens) -----------
rc=0; got="$(PATH="$tmp/empty" NP_DASH_OPENER= np_resolve_opener)" || rc=$?
[[ "$rc" != 0 ]] || { echo "FAIL(none): expected non-zero when no opener present"; exit 1; }
[[ -z "$got" ]] || { echo "FAIL(none): expected empty output, got '$got'"; exit 1; }

echo "PASS test_resolve_opener"
