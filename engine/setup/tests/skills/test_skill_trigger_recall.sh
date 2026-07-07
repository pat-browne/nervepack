#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECALL="$HERE/../../skill-trigger-recall.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

run() { printf '%s' "$1" | NP_SKILL_TRIGGER_STATE="$tmp/state" bash "$RECALL"; }

# Matching: "refactor" near "skill" -> reminder injected
out="$(run "$(jq -nc '{session_id:"s1",prompt:"I want to refactor this skill to be leaner"}')")"
[[ -n "$out" ]] || { echo "FAIL: no output for skill-refactor prompt"; exit 1; }
printf '%s' "$out" | jq -e '.hookSpecificOutput.additionalContext | test("disciplined skill-authoring process")' >/dev/null \
  || { echo "FAIL: host-neutral skill-authoring guidance missing from injection: $out"; exit 1; }

# Once-per-session: same session id should produce no output on second call
out2="$(run "$(jq -nc '{session_id:"s1",prompt:"refactor the skill again"}')")"
[[ -z "$out2" ]] || { echo "FAIL: fired twice for same session: $out2"; exit 1; }

# Matching: SKILL.md reference -> reminder injected (new session)
out3="$(run "$(jq -nc '{session_id:"s2",prompt:"update SKILL.md for the new feature"}')")"
printf '%s' "$out3" | jq -e '.hookSpecificOutput.additionalContext | test("Skill-writing trigger")' >/dev/null \
  || { echo "FAIL: SKILL.md trigger not matched: $out3"; exit 1; }

# Non-matching: unrelated prompt -> silence
out4="$(run "$(jq -nc '{session_id:"s3",prompt:"fix the authentication bug in the API"}')")"
[[ -z "$out4" ]] || { echo "FAIL: fired for unrelated prompt: $out4"; exit 1; }

echo "PASS test_skill_trigger_recall"
