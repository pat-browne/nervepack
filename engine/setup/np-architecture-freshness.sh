#!/usr/bin/env bash
# Advisory freshness check for ARCHITECTURE.md (the cheap high-level map). Flags
# live subsystems that exist in the repo but are NOT referenced in the map — the
# drift that happens when a feature/spec is added without updating the doc. This
# is the structural half of "keep the map honest"; semantic drift still needs a
# human. Deterministic, no LLM. Exit 0 always (advisory): prints one `STALE:` line
# per gap and a final `architecture-freshness: N gap(s)` summary. Run standalone
# after editing the map, or daily from np_skill_maintain.py (cli.py cron skill-maintain).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
ARCH="${ARCH_FILE:-$NP/docs/ARCHITECTURE.md}"
TOGGLES="${ARCH_TOGGLES:-$NP/engine/setup/toggles.conf}"
# Design specs live in the content overlay now, not the engine, and they mix
# engine-feature specs with personal content-feature specs — which the engine's map
# has no business cross-checking. So the spec-drift check (section 2) is OFF by
# default in the engine: it only runs when a caller points ARCH_SPECS_DIR at a specs
# dir it owns (the tests do this; a content-side check could too). The engine map's
# own freshness is section 1 (every toggle/feature is named). Empty SPECS_DIR +
# the -d guard below = a clean no-op.
SPECS_DIR="${ARCH_SPECS_DIR:-}"

[[ -f "$ARCH" ]] || { echo "architecture-freshness: ARCHITECTURE.md missing at $ARCH"; exit 0; }
gaps=0

# 1. Every declared feature toggle must be named in the map's feature catalog.
if [[ -f "$TOGGLES" ]]; then
  while IFS='|' read -r feat _rest; do
    feat="$(printf '%s' "$feat" | tr -d '[:space:]')"
    [[ -z "$feat" || "$feat" == \#* ]] && continue
    grep -q "\`$feat\`" "$ARCH" || { echo "STALE: feature '$feat' (toggles.conf) not in ARCHITECTURE.md"; gaps=$((gaps+1)); }
  done < "$TOGGLES"
fi

# 2. Every design spec must be referenced (mark one-time/historical ones in the
#    map's "read more" so they count as referenced — silence is the drift signal).
if [[ -d "$SPECS_DIR" ]]; then
  shopt -s nullglob
  for s in "$SPECS_DIR"/*-design.md; do
    b="$(basename "$s")"
    grep -q "$b" "$ARCH" || { echo "STALE: spec '$b' not referenced in ARCHITECTURE.md"; gaps=$((gaps+1)); }
  done
fi

echo "architecture-freshness: $gaps gap(s)"
exit 0
