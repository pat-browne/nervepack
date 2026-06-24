#!/usr/bin/env bash
# Manual, on-demand dashboard open. Unlike 74-open-dashboard.sh (the SessionStart
# hook, which opens at most ONCE per OS boot to avoid the remote-desktop reconnect
# loop), this is a deliberate user action — it always rebuilds the data file and
# opens, no boot guard. A single manual xdg-open is not in the SessionStart path,
# so it cannot start the reconnect/re-open loop the hook guards against.
#
# Usage: bash setup/open-dashboard.sh   (NP_DASH_OPENER overrides the opener for tests;
# default is xdg-open on Linux, open on macOS — see np_resolve_opener)
# Fail-open: never hard-errors.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"

# Refresh metrics.js from whatever is in metrics.jsonl (best-effort). build.py
# resolves the content overlay (metrics, wiki/) via np_content_dir; pass the
# wiki-nav param so the left-nav index honors the evaluator.wiki_nav toggle.
# shellcheck source=/dev/null
source "$HERE/np-toggle-lib.sh" 2>/dev/null || true
WIKI_NAV="$(np_param evaluator.wiki_nav on 2>/dev/null || echo on)" \
  WIKI_MERMAID="$(np_param evaluator.wiki_mermaid on 2>/dev/null || echo on)" \
  python3 "$NP/dashboard/build.py" >/dev/null 2>&1 || true

# Resolve the URL (file:// by default; http:// with a local backend when
# evaluator.dashboard_serve is on — the helper starts the server if needed).
# shellcheck source=/dev/null
source "$HERE/np-dashboard-launch.sh"
url="$(np_dashboard_url)"

opener="$(np_resolve_opener || true)"
command -v "$opener" >/dev/null 2>&1 || { echo "no opener (${opener:-none}) found" >&2; exit 0; }
"$opener" "$url" >/dev/null 2>&1 || true
echo "opened $url"
