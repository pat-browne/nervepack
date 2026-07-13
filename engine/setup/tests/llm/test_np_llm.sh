#!/usr/bin/env bash
# Contract test for np-llm.sh — the backend-neutral LLM wrapper the runtime calls
# instead of hardcoding `claude -p`. Black-box via a stub backend (CLAUDE_BIN) that
# records the argv / NERVEPACK_AGENT env / stdin it received.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NPLLM="$HERE/../../np-llm.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
{
  echo "ARGV: $*"
  echo "AGENT=${NERVEPACK_AGENT:-unset}"
  echo "CLAUDECODE=${CLAUDECODE:-unset}"
  echo "SESSION_ID=${CLAUDE_CODE_SESSION_ID:-unset}"
  echo "STDIN: $(cat)"
} > "$STUB_OUT"
printf 'BACKEND_OK'
STUB
chmod +x "$tmp/claude"

# 1. complete: stdin prompt reaches backend; cheap model; empty tools; returns stdout.
out="$(printf 'hello' | CLAUDE_BIN="$tmp/claude" STUB_OUT="$tmp/c" NP_LLM_MODEL_CHEAP=cheapM bash "$NPLLM" complete)"
[[ "$out" == "BACKEND_OK" ]]                || { echo "FAIL: complete didn't return backend stdout: $out"; exit 1; }
grep -q 'STDIN: hello' "$tmp/c"             || { echo "FAIL: prompt not piped to backend stdin"; exit 1; }
grep -q -- '--model cheapM' "$tmp/c"        || { echo "FAIL: cheap model not used: $(cat "$tmp/c")"; exit 1; }
grep -q 'AGENT=1' "$tmp/c"                  || { echo "FAIL: np-llm must set NERVEPACK_AGENT=1 on backend call"; exit 1; }

# 2. complete --system passes the system prompt.
printf 'p' | CLAUDE_BIN="$tmp/claude" STUB_OUT="$tmp/s" bash "$NPLLM" complete --system "SYSPROMPT" >/dev/null
grep -q -- '--append-system-prompt SYSPROMPT' "$tmp/s" || { echo "FAIL: --system not forwarded: $(cat "$tmp/s")"; exit 1; }

# 3. agent: bypass perms, agent model, the requested tools, guard set, --bare to suppress hooks.
printf 'task' | CLAUDE_BIN="$tmp/claude" STUB_OUT="$tmp/a" NP_LLM_MODEL_AGENT=agentM bash "$NPLLM" agent --tools "Bash Read Write" >/dev/null
grep -q 'bypassPermissions' "$tmp/a"        || { echo "FAIL: agent missing bypassPermissions"; exit 1; }
grep -q -- '--model agentM' "$tmp/a"        || { echo "FAIL: agent model not used"; exit 1; }
grep -q 'Bash Read Write' "$tmp/a"          || { echo "FAIL: agent tools not forwarded: $(cat "$tmp/a")"; exit 1; }
grep -q 'AGENT=1' "$tmp/a"                  || { echo "FAIL: agent must set NERVEPACK_AGENT=1"; exit 1; }
grep -q -- '--bare' "$tmp/a"                || { echo "FAIL: agent must pass --bare to suppress third-party hooks (see sdd/investigate-implement.md): $(cat "$tmp/a")"; exit 1; }

# 3b. complete: --bare NOT passed; keychain auth must work (--allowedTools "" means no
#     tool use, so PostToolUse hooks can't fire; NERVEPACK_AGENT=1 handles recursion).
printf 'hello' | CLAUDE_BIN="$tmp/claude" STUB_OUT="$tmp/cb" NP_LLM_MODEL_CHEAP=cheapM bash "$NPLLM" complete >/dev/null
grep -q -- '--bare' "$tmp/cb" && { echo "FAIL: complete must NOT pass --bare (breaks keychain auth on Windows): $(cat "$tmp/cb")"; exit 1; } || true

# 3c. local backend: --bare is NOT passed (local backend has no claude hooks).
# Intercept the `python3 <path>/np-llm-local.py` call by prepending a stub python3 to
# PATH. The stub records its full argv (which includes the np-llm-local.py path and the
# mode arg) so we can assert: (a) the local path actually ran (record file written —
# guards against a vacuous pass), and (b) --bare does NOT appear in the argv.
mkdir -p "$tmp/stub-bin"
cat > "$tmp/stub-bin/python3" <<'PYSTUB'
#!/usr/bin/env bash
# Invoked as: python3 /full/path/to/np-llm-local.py complete [--system ...]
# Record full argv so the caller can assert on it.
printf 'ARGV: %s\n' "$@" > "$LOCAL_ARGV_OUT"
printf 'LOCAL_OK'
PYSTUB
chmod +x "$tmp/stub-bin/python3"
printf 'hello' | CLAUDE_BIN="$tmp/claude" LOCAL_ARGV_OUT="$tmp/lc" \
  NP_LLM_BACKEND=local NP_LLM_BASE_URL=http://localhost \
  PATH="$tmp/stub-bin:$PATH" bash "$NPLLM" complete >/dev/null 2>&1
# Guard against vacuous pass: the stub MUST have been called (record file written).
[[ -s "$tmp/lc" ]] || { echo "FAIL: local backend path was never exercised (stub argv file not written)"; exit 1; }
# The real assertion: --bare must NOT appear in the local backend call.
grep -q -- '--bare' "$tmp/lc" && { echo "FAIL: --bare must NOT appear in local backend call: $(cat "$tmp/lc")"; exit 1; } || true

# 3d. a caller running inside an inherited Claude Code session (e.g. the dashboard
#     server, backgrounded from a SessionStart hook and long-outliving it) must not
#     leak that session's identity into the nested backend call — the child would
#     otherwise be mistaken for a child of a possibly-stale session and fail auth
#     ("Not logged in") instead of authenticating as its own top-level headless run.
out="$(printf 'hello' | CLAUDECODE=1 CLAUDE_CODE_SESSION_ID=stale-parent-session \
  CLAUDE_CODE_ENTRYPOINT=cli CLAUDE_CODE_CHILD_SESSION=1 \
  CLAUDE_BIN="$tmp/claude" STUB_OUT="$tmp/leak" bash "$NPLLM" complete)"
[[ "$out" == "BACKEND_OK" ]]                       || { echo "FAIL: complete didn't return backend stdout under inherited session env: $out"; exit 1; }
grep -q 'CLAUDECODE=unset' "$tmp/leak"             || { echo "FAIL: CLAUDECODE leaked into nested claude call: $(cat "$tmp/leak")"; exit 1; }
grep -q 'SESSION_ID=unset' "$tmp/leak"             || { echo "FAIL: CLAUDE_CODE_SESSION_ID leaked into nested claude call: $(cat "$tmp/leak")"; exit 1; }

printf 'task' | CLAUDECODE=1 CLAUDE_CODE_SESSION_ID=stale-parent-session \
  CLAUDE_BIN="$tmp/claude" STUB_OUT="$tmp/leak2" bash "$NPLLM" agent --tools "Bash" >/dev/null
grep -q 'CLAUDECODE=unset' "$tmp/leak2"            || { echo "FAIL: CLAUDECODE leaked into nested agent call: $(cat "$tmp/leak2")"; exit 1; }
grep -q 'SESSION_ID=unset' "$tmp/leak2"            || { echo "FAIL: CLAUDE_CODE_SESSION_ID leaked into nested agent call: $(cat "$tmp/leak2")"; exit 1; }

# 4. unknown backend fails loudly (non-zero), doesn't silently no-op.
set +e
printf 'p' | NP_LLM_BACKEND=bogus bash "$NPLLM" complete >/dev/null 2>&1; rc=$?
set -e
[[ $rc -ne 0 ]] || { echo "FAIL: unknown backend should exit non-zero"; exit 1; }

echo "PASS test_np_llm"
