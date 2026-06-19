#!/usr/bin/env bash
# Deterministic stand-in for np-implement-suggestion.sh in e2e. Writes the per-suggestion
# status file the server polls (keyed by sha256(text)[:16]), with the state the test
# selected via NP_STUB_STATE (done|not_implementable|failed). NEVER calls a real LLM/agent.
set -euo pipefail
text="$1"
key="$(printf '%s' "$text" | python3 -c 'import sys,hashlib;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])')"
mkdir -p "$NP_IMPLEMENT_STATUS_DIR"
state="${NP_STUB_STATE:-done}"
ref=""; [[ "$state" == "done" ]] && ref="https://github.com/pat-browne/nervepack/pull/999"
printf '{"state":"%s","ref":"%s"}\n' "$state" "$ref" > "$NP_IMPLEMENT_STATUS_DIR/$key.json"
