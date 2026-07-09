#!/usr/bin/env bash
# Asserts the engine-self-knowledge slices that relocating kb skills used to carry
# are present in the manual, so the crons/hooks/prompts don't depend on a delivered skill.
#
# The evaluator-signals line intentionally asserts on "zero-bias" — the distinctive
# term np-kb-evaluator-signals/SKILL.md uses to teach *why* a deterministic signal
# reads zero (structural vs. real gap). That phrase does not appear anywhere in the
# manual before Task 2 folds the skill's field-by-field taxonomy into
# docs/FEATURES.md, so this line is a genuine RED before the fold — unlike the other
# slices below, which were already fully present and are asserted here as a guard
# against regression, not as new RED.
set -uo pipefail
NP="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail=0
need() { grep -RIliq -- "$1" "$NP/AGENTS.md" "$NP/docs/ARCHITECTURE.md" "$NP/docs/FEATURES.md" \
  || { echo "MISSING from manual: $2"; fail=1; }; }
need "no LLM attribution\|no.*AI.*trailer\|Co-Authored"        "coding-rules §6 (no-AI-trailer)"
need "fail open\|fail-open"                                     "coding-rules §8 / inv1 (fail-open)"
need "NERVEPACK_AGENT"                                          "headless recursion guard"
need "stdin"                                                    "headless stdin-not-positional"
need "zero-dep\|stdlib"                                         "testing-ci zero-dep policy"
need "zero-bias"                                                "evaluator-signals field-by-field taxonomy"
[[ $fail -eq 0 ]] && echo "PASS test_self_knowledge_folded" || { echo "FAIL test_self_knowledge_folded"; exit 1; }
