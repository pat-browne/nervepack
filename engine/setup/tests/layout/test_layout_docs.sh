#!/usr/bin/env bash
# np-test: layout | happy
# nervepack#234: the ENGINE must not instruct anyone to write into one overlay's
# directory tree. Paths come from the layer's own layout manifest.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"

fail() { echo "FAIL test_layout_docs: $1" >&2; exit 1; }

# Scope: the CONTRIBUTION instructions -- the engine telling an agent where to
# WRITE. np-core-layout's reference doc is exempt (it shows example manifests), and
# so are the dashboard's wiki indexer and the MCP resource URIs, which READ a tree
# rather than route a write.
for f in "$REPO/skills/np-core-contribute/SKILL.md" \
         "$REPO/skills/np-core-contribute/references/classification.md" \
         "$REPO/skills/np-core-capture-learning/SKILL.md"; do
  hits=$(grep -n 'wiki/topics/\|wiki/concepts/' "$f" 2>/dev/null || true)
  [[ -z "$hits" ]] || fail "hardcoded overlay write paths remain in $f:
$hits"
done

# The content seam must describe layouts, not one overlay's tree.
grep -q 'layout.json' "$REPO/docs/ARCHITECTURE.md" \
  || fail "ARCHITECTURE.md does not document the layout manifest"

# contribute must route through the resolver, not a path table.
grep -qE 'layout route|np-core-layout' "$REPO/skills/np-core-contribute/SKILL.md" \
  || fail "np-core-contribute does not reference the layout resolver"

# contribute must require an inbound link (the findability half of the contract).
grep -qiE 'inbound link|links to it|wikilink' "$REPO/skills/np-core-contribute/SKILL.md" \
  || fail "np-core-contribute does not require an inbound link"

# onboard must run layout discovery per layer.
grep -qi 'layout' "$REPO/skills/np-core-onboard/SKILL.md" \
  || fail "np-core-onboard has no layout step"

# The onboard contract must name the capability.
grep -q 'layer-layout' "$REPO/engine/onboard/ONBOARD.md" \
  || fail "ONBOARD.md does not mention layer-layout"

echo "PASS test_layout_docs"
