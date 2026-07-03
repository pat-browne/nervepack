#!/usr/bin/env bash
# np-test: lessons | regression
# Regression coverage for lesson-recall.sh (merge of playbook-recall.sh +
# strategy-recall.sh): topic_triggers matching against memory/lessons/,
# provenance-framed injection (failure -> imperative "past failure pattern",
# success -> advisory "approach that worked"), a topic file carrying BOTH
# provenances surfaced with BOTH framings, the tool_name_match armed-marker
# handoff to lesson-guard.sh Phase 2, and fail-open no-match silence.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECALL="$HERE/../../lesson-recall.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/lessons"

cat > "$tmp/lessons/INDEX.md" <<'IDX'
| topic | tool_match | gate | topic_triggers |
|---|---|---|---|
| bulk-rename |  | warn | rename, sed |
| deploydance |  |  | deploy, rename |
IDX

cat > "$tmp/lessons/bulk-rename.md" <<'LESSON'
---
name: bulk-rename
kind: lesson
provenance: failure
status: confirmed
seen: 3
last_updated: 2026-06-01
topic_triggers: [rename, sed]
wiki: []
---
**Do:** guarded single pass; residual-grep verify.
**Avoid:** blanket bare-word replace.
LESSON

cat > "$tmp/lessons/deploydance.md" <<'LESSON'
---
name: deploydance
kind: lesson
provenance: success
status: confirmed
seen: 2
last_updated: 2026-06-01
topic_triggers: [deploy, rename]
wiki: []
---
**Title:** Mirror the proven deploy dance
**When:** shipping a rename-heavy release
**Do:** run the checklist before touching prod.
LESSON

run() { printf '%s' "$1" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$tmp/st" bash "$RECALL"; }

# Matching prompt hits BOTH a failure-provenance topic and a success-provenance
# topic on a shared trigger keyword ("rename") -> both entries injected, each
# with its own provenance-specific framing verb.
out="$(run "$(jq -nc '{session_id:"s1",prompt:"need to do a bulk rename before we deploy"}')")"
ctx="$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty')"
[[ -n "$ctx" ]] || { echo "FAIL: no context injected: $out"; exit 1; }

printf '%s' "$ctx" | grep -qi 'bulk-rename' || { echo "FAIL: failure entry missing: $ctx"; exit 1; }
printf '%s' "$ctx" | grep -qi 'guarded single pass' || { echo "FAIL: failure body missing: $ctx"; exit 1; }
printf '%s' "$ctx" | grep -qiE 'past failure' || { echo "FAIL: failure framing verb missing: $ctx"; exit 1; }

printf '%s' "$ctx" | grep -qi 'deploydance' || { echo "FAIL: success entry missing: $ctx"; exit 1; }
printf '%s' "$ctx" | grep -qi 'Mirror the proven deploy dance' || { echo "FAIL: success body missing: $ctx"; exit 1; }
printf '%s' "$ctx" | grep -qiE 'worked' || { echo "FAIL: success framing verb missing: $ctx"; exit 1; }

# Non-matching prompt -> silent (fail-open, no injection).
miss="$(run "$(jq -nc '{session_id:"s2",prompt:"what is the weather today"}')")"
[[ -z "$miss" ]] || { echo "FAIL: no-match not silent: $miss"; exit 1; }

# A single merged topic file carrying BOTH provenances (a topic that was in
# both playbooks AND strategies pre-merge) -> each block surfaced with its
# own framing from the SAME file/topic.
cat > "$tmp/lessons/gitflow.md" <<'LESSON'
---
name: gitflow
kind: lesson
provenance: failure
status: confirmed
seen: 4
last_updated: 2026-06-01
topic_triggers: [merge]
enforce:
  tool_match: "git merge"
  gate: warn
wiki: []
---
**Do:** rebase onto main before merging.
**Avoid:** merging without rebasing first.
---
name: gitflow
kind: lesson
provenance: success
status: confirmed
seen: 2
last_updated: 2026-06-01
topic_triggers: [merge]
wiki: []
---
**Title:** Squash-merge feature branches
**When:** landing a reviewed feature branch
**Do:** squash-merge to keep history linear.
LESSON
cat >> "$tmp/lessons/INDEX.md" <<'IDX'
| gitflow | git merge | warn | merge |
IDX

out2="$(run "$(jq -nc '{session_id:"s3",prompt:"about to merge this branch"}')")"
ctx2="$(printf '%s' "$out2" | jq -r '.hookSpecificOutput.additionalContext // empty')"
printf '%s' "$ctx2" | grep -qi 'rebase onto main' || { echo "FAIL: merged-file failure body missing: $ctx2"; exit 1; }
printf '%s' "$ctx2" | grep -qi 'Squash-merge feature branches' || { echo "FAIL: merged-file success body missing: $ctx2"; exit 1; }
printf '%s' "$ctx2" | grep -qiE 'past failure' || { echo "FAIL: merged-file failure framing missing: $ctx2"; exit 1; }
printf '%s' "$ctx2" | grep -qiE 'worked' || { echo "FAIL: merged-file success framing missing: $ctx2"; exit 1; }

# Armed-marker handoff: a failure-provenance topic with enforce.tool_name_match
# arms a marker lesson-guard.sh Phase 2 checks for.
cat > "$tmp/lessons/sec-review.md" <<'LESSON'
---
name: sec-review
kind: lesson
provenance: failure
status: confirmed
seen: 1
last_updated: 2026-06-01
topic_triggers: [security, review]
enforce:
  tool_match: ""
  tool_name_match: "Read"
  gate: ask
wiki: []
---
**Do:** invoke the skill first.
LESSON
cat >> "$tmp/lessons/INDEX.md" <<'IDX'
| sec-review |  | ask | security, review |
IDX

run "$(jq -nc '{session_id:"s4",prompt:"please do a security review of this code"}')" >/dev/null
[[ -f "$tmp/st/s4-sec-review-gate-armed" ]] || { echo "FAIL: armed marker not written for tool_name_match lesson"; exit 1; }

echo "PASS test_lesson_recall"
