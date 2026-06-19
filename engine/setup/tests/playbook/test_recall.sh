#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECALL="$HERE/../../playbook-recall.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/playbooks"
cat > "$tmp/playbooks/INDEX.md" <<'IDX'
| topic | tool_match | gate | topic_triggers | seen |
|---|---|---|---|---:|
| bulk-rename |  | warn | rename, sed, findreplace | 3 |
IDX
cat > "$tmp/playbooks/bulk-rename.md" <<'PB'
---
name: bulk-rename
---
**Do:** guarded single pass; residual-grep verify.
PB
# Playbook with tool_name_match for armed-marker test
cat >> "$tmp/playbooks/INDEX.md" <<'IDX'
| sec-gate |  | warn | security, review | 5 |
IDX
cat > "$tmp/playbooks/sec-gate.md" <<'PB'
---
name: sec-gate
kind: playbook
enforce:
  tool_match: ""
  tool_name_match: "Read"
  gate: ask
  topic_triggers: [security, review]
---
**Do:** invoke the skill first.
PB
run() { printf '%s' "$1" | EPISODIC_PLAYBOOK_DIR="$tmp/playbooks" EPISODIC_STATE_DIR="$tmp/st" bash "$RECALL"; }

out="$(run "$(jq -nc '{session_id:"s1",prompt:"help me do a bulk rename across the repo"}')")"
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | test("Before proceeding")' >/dev/null || { echo "FAIL: not imperative: $out"; exit 1; }
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | test("bulk-rename")' >/dev/null || { echo "FAIL: playbook missing: $out"; exit 1; }

miss="$(run "$(jq -nc '{session_id:"s2",prompt:"what is the weather"}')")"
[[ -z "$miss" ]] || { echo "FAIL: no-match not silent: $miss"; exit 1; }

# Armed-marker test: security keyword triggers sec-gate playbook → marker written
out2="$(run "$(jq -nc '{session_id:"s3",prompt:"please do a security review of this code"}')")"
[[ -f "$tmp/st/s3-sec-gate-gate-armed" ]] || { echo "FAIL: armed marker not written for tool_name_match playbook: $out2"; exit 1; }

# Non-matching prompt → no armed marker
[[ ! -f "$tmp/st/s4-sec-gate-gate-armed" ]] || { echo "FAIL: armed marker written for non-matching prompt"; exit 1; }
run "$(jq -nc '{session_id:"s4",prompt:"add a button to the UI"}')" >/dev/null || true
[[ ! -f "$tmp/st/s4-sec-gate-gate-armed" ]] || { echo "FAIL: armed marker written for unrelated prompt"; exit 1; }

echo "PASS test_playbook_recall"
