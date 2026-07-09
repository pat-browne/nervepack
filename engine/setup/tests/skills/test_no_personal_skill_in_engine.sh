#!/usr/bin/env bash
# No company/personal-named skill may live in the public engine tree.
set -uo pipefail
NP="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
hit="$(ls "$NP/skills" | grep -iE 'campminder|pbrowne|wiresandwizards' || true)"
[[ -z "$hit" ]] && echo "PASS test_no_personal_skill_in_engine" || { echo "FAIL: personal-named skill in engine: $hit"; exit 1; }
