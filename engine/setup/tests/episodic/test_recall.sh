#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECALL="$HERE/../../episodic-recall.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/episodic"
cat > "$tmp/episodic/INDEX.md" <<'IDX'
| topic | last_updated | keywords | lines |
|---|---|---|---:|
| auth-patterns | 2026-06-02 | oauth, login, token | 20 |
IDX
cat > "$tmp/episodic/auth-patterns.md" <<'TOP'
---
name: auth-patterns
kind: episodic
---
# Auth patterns
## [2026-06-02] proj — wired oauth login
We finished the oauth login redirect.
TOP

payload="$(jq -nc '{session_id:"sess1", prompt:"fix the oauth login bug"}')"
run() { printf '%s' "$payload" | EPISODIC_DIR="$tmp/episodic" EPISODIC_STATE_DIR="$tmp/state" bash "$RECALL"; }

out1="$(run)"
echo "$out1" | jq -e '.hookSpecificOutput.additionalContext | test("auth-patterns")' >/dev/null \
  || { echo "FAIL: first prompt did not inject theme: $out1"; exit 1; }

_=$(run)                 # second prompt (count → 2)
out3="$(run)"            # third prompt: must be silent
[[ -z "$out3" ]] || { echo "FAIL: expected silence after opening prompts, got: $out3"; exit 1; }

miss="$(printf '%s' "$(jq -nc '{session_id:"sess2", prompt:"weather forecast"}')" | EPISODIC_DIR="$tmp/episodic" EPISODIC_STATE_DIR="$tmp/state" bash "$RECALL")"
[[ -z "$miss" ]] || { echo "FAIL: expected no-match silence, got: $miss"; exit 1; }

echo "PASS test_recall"
