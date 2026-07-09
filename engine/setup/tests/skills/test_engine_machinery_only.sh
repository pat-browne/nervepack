#!/usr/bin/env bash
# The engine skills/ tree must contain ONLY machinery: np-core-* and np-flow-*.
set -uo pipefail
NP="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
bad="$(ls "$NP/skills" | grep -vE '^np-core-|^np-flow-' || true)"
[[ -z "$bad" ]] && echo "PASS test_engine_machinery_only" || { echo "FAIL: non-machinery skills in engine: $bad"; exit 1; }
