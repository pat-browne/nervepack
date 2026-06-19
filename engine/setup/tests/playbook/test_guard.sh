#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HERE/../../playbook-guard.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/playbooks"
cat > "$tmp/playbooks/INDEX.md" <<'IDX'
| topic | tool_match | gate | topic_triggers | seen |
|---|---|---|---|---:|
| bulk-rename | sed -i .*s[#/] | warn | rename, sed | 3 |
| nuke | rm -rf | ask | delete, cleanup | 2 |
IDX
cat > "$tmp/playbooks/bulk-rename.md" <<'PB'
---
name: bulk-rename
kind: playbook
---
**Do:** guarded single pass; residual-grep verify.
**Avoid:** blanket bare-word replace.
PB
cat > "$tmp/playbooks/nuke.md" <<'PB'
---
name: nuke
kind: playbook
---
**Avoid:** rm -rf without an explicit, checked path.
PB
st="$(mktemp -d)"; trap 'rm -rf "$tmp" "$st"' EXIT
run() { printf '%s' "$1" | EPISODIC_PLAYBOOK_DIR="$tmp/playbooks" EPISODIC_STATE_DIR="$st" bash "$GUARD"; }

out="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"sed -i \"s#a#b#\" f"}}')")"
echo "$out" | jq -e '.hookSpecificOutput.permissionDecision == "allow"' >/dev/null || { echo "FAIL: warn not allow: $out"; exit 1; }
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | test("guarded single pass")' >/dev/null || { echo "FAIL: warn missing context: $out"; exit 1; }

out2="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"rm -rf /tmp/x"}}')")"
echo "$out2" | jq -e '.hookSpecificOutput.permissionDecision == "ask"' >/dev/null || { echo "FAIL: destructive not ask: $out2"; exit 1; }
echo "$out2" | jq -e '.hookSpecificOutput.permissionDecisionReason | test("rm -rf without an explicit")' >/dev/null || { echo "FAIL: ask missing reason: $out2"; exit 1; }

out3="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"ls -la"}}')")"
[[ -z "$out3" ]] || { echo "FAIL: non-match emitted output: $out3"; exit 1; }

out4="$(printf '%s' "$(jq -nc '{tool_name:"Bash",tool_input:{command:"rm -rf /"}}')" | EPISODIC_PLAYBOOK_DIR="$tmp/none" bash "$GUARD")"
[[ -z "$out4" ]] || { echo "FAIL: missing index not fail-open: $out4"; exit 1; }

# Phase 2: Read tool_name_match gate — armed marker present → ask gate fires once
cat > "$tmp/playbooks/sec-review.md" <<'PB'
---
name: sec-review
kind: playbook
enforce:
  tool_name_match: "Read"
  gate: ask
---
**Do:** invoke the skill first.
PB
touch "$st/s1-sec-review-gate-armed"
out5="$(printf '%s' "$(jq -nc '{tool_name:"Read",session_id:"s1",tool_input:{file_path:"/some/file.py"}}')" | EPISODIC_PLAYBOOK_DIR="$tmp/playbooks" EPISODIC_STATE_DIR="$st" bash "$GUARD")"
echo "$out5" | jq -e '.hookSpecificOutput.permissionDecision == "ask"' >/dev/null || { echo "FAIL: Read gate not ask: $out5"; exit 1; }
# Marker removed after firing (one-shot)
[[ ! -f "$st/s1-sec-review-gate-armed" ]] || { echo "FAIL: armed marker not removed after fire"; exit 1; }

# Without armed marker, Read call passes through silently
out6="$(printf '%s' "$(jq -nc '{tool_name:"Read",session_id:"s1",tool_input:{file_path:"/other/file.py"}}')" | EPISODIC_PLAYBOOK_DIR="$tmp/playbooks" EPISODIC_STATE_DIR="$st" bash "$GUARD")"
[[ -z "$out6" ]] || { echo "FAIL: unarmed Read gate emitted output: $out6"; exit 1; }

echo "PASS test_guard"
