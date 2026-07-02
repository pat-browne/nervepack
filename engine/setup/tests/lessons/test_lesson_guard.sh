#!/usr/bin/env bash
# np-test: lessons | regression
# Regression coverage for lesson-guard.sh (renamed from playbook-guard.sh):
# Phase 1 (Bash command vs INDEX.md tool_match), Phase 2 (armed non-Bash
# tool_name_match gate), the fail-open missing-index path, and the default
# memory/lessons/ resolution via np_layer_dir. Mirrors the pre-rename
# test_guard.sh coverage 1:1, over memory/lessons instead of memory/playbooks.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HERE/../../lesson-guard.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/lessons"
cat > "$tmp/lessons/INDEX.md" <<'IDX'
| topic | tool_match | gate | topic_triggers |
|---|---|---|---|
| bulk-rename | sed -i .*s[#/] | warn | rename, sed |
| nuke | rm -rf | ask | delete, cleanup |
IDX
cat > "$tmp/lessons/bulk-rename.md" <<'LESSON'
---
name: bulk-rename
kind: lesson
provenance: failure
---
**Do:** guarded single pass; residual-grep verify.
**Avoid:** blanket bare-word replace.
LESSON
cat > "$tmp/lessons/nuke.md" <<'LESSON'
---
name: nuke
kind: lesson
provenance: failure
---
**Avoid:** rm -rf without an explicit, checked path.
LESSON
st="$(mktemp -d)"; trap 'rm -rf "$tmp" "$st"' EXIT
run() { printf '%s' "$1" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$st" bash "$GUARD"; }

out="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"sed -i \"s#a#b#\" f"}}')")"
echo "$out" | jq -e '.hookSpecificOutput.permissionDecision == "allow"' >/dev/null || { echo "FAIL: warn not allow: $out"; exit 1; }
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | test("guarded single pass")' >/dev/null || { echo "FAIL: warn missing context: $out"; exit 1; }

out2="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"rm -rf /tmp/x"}}')")"
echo "$out2" | jq -e '.hookSpecificOutput.permissionDecision == "ask"' >/dev/null || { echo "FAIL: destructive not ask: $out2"; exit 1; }
echo "$out2" | jq -e '.hookSpecificOutput.permissionDecisionReason | test("rm -rf without an explicit")' >/dev/null || { echo "FAIL: ask missing reason: $out2"; exit 1; }

out3="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"ls -la"}}')")"
[[ -z "$out3" ]] || { echo "FAIL: non-match emitted output: $out3"; exit 1; }

out4="$(printf '%s' "$(jq -nc '{tool_name:"Bash",tool_input:{command:"rm -rf /"}}')" | EPISODIC_LESSON_DIR="$tmp/none" bash "$GUARD")"
[[ -z "$out4" ]] || { echo "FAIL: missing index not fail-open: $out4"; exit 1; }

# Phase 2: Read tool_name_match gate — armed marker present → ask gate fires once
cat > "$tmp/lessons/sec-review.md" <<'LESSON'
---
name: sec-review
kind: lesson
provenance: failure
enforce:
  tool_name_match: "Read"
  gate: ask
---
**Do:** invoke the skill first.
LESSON
touch "$st/s1-sec-review-gate-armed"
out5="$(printf '%s' "$(jq -nc '{tool_name:"Read",session_id:"s1",tool_input:{file_path:"/some/file.py"}}')" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$st" bash "$GUARD")"
echo "$out5" | jq -e '.hookSpecificOutput.permissionDecision == "ask"' >/dev/null || { echo "FAIL: Read gate not ask: $out5"; exit 1; }
# Marker removed after firing (one-shot)
[[ ! -f "$st/s1-sec-review-gate-armed" ]] || { echo "FAIL: armed marker not removed after fire"; exit 1; }

# Without armed marker, Read call passes through silently
out6="$(printf '%s' "$(jq -nc '{tool_name:"Read",session_id:"s1",tool_input:{file_path:"/other/file.py"}}')" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$st" bash "$GUARD")"
[[ -z "$out6" ]] || { echo "FAIL: unarmed Read gate emitted output: $out6"; exit 1; }

# Default-path case: NP_CONTENT_DIR set, EPISODIC_LESSON_DIR NOT set.
# Guard must read from memory/lessons/ (via np_layer_dir).
tmp2="$(mktemp -d)"; trap 'rm -rf "$tmp" "$st" "$tmp2"' EXIT
mkdir -p "$tmp2/memory/lessons"
cat > "$tmp2/memory/lessons/INDEX.md" <<'IDX'
| topic | tool_match | gate | topic_triggers |
|---|---|---|---|
| force-push | git push.*--force | ask | force, push |
IDX
cat > "$tmp2/memory/lessons/force-push.md" <<'LESSON'
---
name: force-push
kind: lesson
provenance: failure
---
**Avoid:** force-pushing without checking the remote first.
LESSON
out7="$(printf '%s' "$(jq -nc '{tool_name:"Bash",tool_input:{command:"git push --force origin main"}}')" \
  | NP_CONTENT_DIR="$tmp2" EPISODIC_STATE_DIR="$st" bash "$GUARD")"
echo "$out7" | jq -e '.hookSpecificOutput.permissionDecision == "ask"' >/dev/null \
  || { echo "FAIL: default memory/lessons not read (guard did not fire): $out7"; exit 1; }
echo "$out7" | jq -e '.hookSpecificOutput.permissionDecisionReason | test("force-pushing")' >/dev/null \
  || { echo "FAIL: default memory/lessons ask missing reason: $out7"; exit 1; }

echo "PASS test_lesson_guard"
