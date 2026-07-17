#!/usr/bin/env bash
# Asserts np_skill_budget.py scans BOTH engine and overlay skill roots.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; SETUP="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/engine/skills/np-core-x" "$tmp/overlay/skills/np-kb-y"
printf -- '---\nname: np-core-x\ndescription: d\n---\nbody\n' > "$tmp/engine/skills/np-core-x/SKILL.md"
# oversized overlay skill (> hard split) to force it into the report
{ printf -- '---\nname: np-kb-y\ndescription: d\n---\n'; head -c 9000 /dev/zero | tr '\0' 'x'; } > "$tmp/overlay/skills/np-kb-y/SKILL.md"
out="$(python3 "$SETUP/np_skill_budget.py" "$tmp/engine/skills" "$tmp/overlay/skills" 2>/dev/null)"
echo "$out" | grep -q 'np-kb-y' || { echo "FAIL: overlay skill not scanned: $out"; exit 1; }
echo "PASS test_skill_maintain_roots"
