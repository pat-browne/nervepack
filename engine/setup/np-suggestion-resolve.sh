#!/usr/bin/env bash
# Mark an evaluator suggestion as acted-on so the metrics dashboard stops resurfacing
# it. Appends the suggestion text to dashboard/data/resolved-suggestions.txt (deduped,
# case/space-insensitive) and rebuilds metrics.js so the dashboard reflects it now.
# build.py filters any suggestion whose normalized text is in that ledger.
#
# Usage: np-suggestion-resolve.sh "<suggestion text, as shown on the dashboard>"
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
source "$HERE/np-content-lib.sh"
LEDGER="${NP_RESOLVED_SUGGESTIONS:-$(np_content_dir)/dashboard/data/resolved-suggestions.txt}"

text="${1:-}"
[[ -n "$text" ]] || { echo "usage: np-suggestion-resolve.sh \"<suggestion text>\"" >&2; exit 2; }

norm() { printf '%s' "${1%%	*}" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//'; }
target="$(norm "$text")"

mkdir -p "$(dirname "$LEDGER")"; touch "$LEDGER"
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  [[ "$(norm "$line")" == "$target" ]] && { echo "already resolved: $text"; exit 0; }
done < "$LEDGER"

# Append with an ISO-8601 timestamp (tab-separated) so the retention pruner can age
# out old entries. build.py load_resolved() strips the \t<ts> suffix before matching.
printf '%s\t%s\n' "$text" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LEDGER"
echo "resolved: $text"

# Rebuild metrics.js so the dashboard drops it immediately (best-effort).
[[ "${NP_RESOLVE_NO_BUILD:-0}" == "1" ]] || python3 "$NP/dashboard/build.py" >/dev/null 2>&1 || true
