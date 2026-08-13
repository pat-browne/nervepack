#!/usr/bin/env bash
# np-test: layout | happy
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
SKILL="$REPO/skills/np-core-layout/SKILL.md"

fail() { echo "FAIL test_layout_skill: $1" >&2; exit 1; }

[[ -f "$SKILL" ]] || fail "missing $SKILL"
grep -q '^name: np-core-layout$' "$SKILL" || fail "frontmatter name missing"
grep -q '^description: ' "$SKILL" || fail "frontmatter description missing"

# The reprocessing rule is nervepack#234's core requirement -- it must be stated.
grep -qi 'one question' "$SKILL" || fail "interview must state the one-question rule"
grep -qiE 're-run|reprocess' "$SKILL" || fail "interview must state the re-run rule"

# Skill body budget (hard limit 8192 bytes).
size=$(wc -c < "$SKILL")
(( size <= 8192 )) || fail "SKILL.md is ${size}b, over the 8192b hard limit"

# The depth file the body points at must exist.
[[ -f "$REPO/skills/np-core-layout/references/interview.md" ]] \
  || fail "references/interview.md missing"

# The engine plugin manifest must list it, or a fresh host never links it.
grep -q 'skills/np-core-layout' "$REPO/.claude-plugin/plugin.json" \
  || fail "plugin.json does not list np-core-layout"

echo "PASS test_layout_skill"
