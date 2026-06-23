#!/usr/bin/env bash
# Regression for np-session-flush.sh (the on-exit promotion step). Two properties:
#  1. RE-ENTRY GUARD: with NERVEPACK_AGENT set it must bail immediately and do NO
#     work (no "flush start" logged) — else the maintain step's claude -p re-fires
#     SessionEnd and we rebuild the recursion loop.
#  2. NORMAL: foreground (NP_FLUSH_NODETACH=1) with empty inboxes + a stub claude,
#     it runs both sub-steps and exits 0 (idempotent no-op, no git, no agent).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUSH="$HERE/../../np-session-flush.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/eval-inbox" "$tmp/ep-inbox"          # empty inboxes -> both steps no-op
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null 2>&1 || true
exit 0
STUB
chmod +x "$tmp/claude"

common=( CLAUDE_BIN="$tmp/claude" EVAL_INBOX="$tmp/eval-inbox" EPISODIC_INBOX="$tmp/ep-inbox"
         METRICS_FILE="$tmp/metrics.jsonl" NP_AGG_NO_COMMIT=1
         EPISODIC_MAINTAIN_LOG="$tmp/maintain.log" NP_FLUSH_NODETACH=1 )

# 1. Guard: NERVEPACK_AGENT set -> immediate bail, nothing logged.
set +e
env "${common[@]}" NERVEPACK_AGENT=1 SESSION_FLUSH_LOG="$tmp/guard.log" bash "$FLUSH"; rc=$?
set -e
[[ $rc -eq 0 ]] || { echo "FAIL: guarded flush must exit 0, got $rc"; exit 1; }
[[ ! -s "$tmp/guard.log" ]] || { echo "FAIL: guarded flush did work (logged): $(cat "$tmp/guard.log")"; exit 1; }

# 2. Normal foreground run: both steps run, exit 0, start+done logged.
set +e
env "${common[@]}" SESSION_FLUSH_LOG="$tmp/flush.log" bash "$FLUSH"; rc=$?
set -e
[[ $rc -eq 0 ]] || { echo "FAIL: flush must exit 0, got $rc"; exit 1; }
grep -q 'flush start' "$tmp/flush.log" || { echo "FAIL: no 'flush start' logged"; exit 1; }
grep -q 'flush done'  "$tmp/flush.log" || { echo "FAIL: flush did not complete"; exit 1; }

# 3. macOS DETACH path (no setsid): the flush must background its slow sub-steps and
#    return instantly, NOT run them synchronously (which got the SessionEnd hook
#    cancelled on macOS). Force the fallback with NP_FLUSH_NO_SETSID=1 so Linux CI
#    exercises it too. Copy the flush beside stub sub-steps that sleep, so a
#    synchronous run is observably slow and a detached run returns before they finish.
det="$tmp/det"; mkdir -p "$det"
cp "$FLUSH" "$det/np-session-flush.sh"
for s in 73-aggregate-metrics.sh 72-run-episodic-maintain.sh; do
  cat > "$det/$s" <<STUB
#!/usr/bin/env bash
sleep 3
touch "$det/ran-\${0##*/}"
STUB
  chmod +x "$det/$s"
done
start=$(date +%s)
set +e
env SESSION_FLUSH_LOG="$det/flush.log" NP_FLUSH_NO_SETSID=1 bash "$det/np-session-flush.sh"; rc=$?
set -e
elapsed=$(( $(date +%s) - start ))
[[ $rc -eq 0 ]] || { echo "FAIL: detached flush must exit 0, got $rc"; exit 1; }
[[ $elapsed -lt 2 ]] || { echo "FAIL: flush blocked ${elapsed}s — did not detach (ran sub-steps synchronously)"; exit 1; }
[[ ! -e "$det/ran-73-aggregate-metrics.sh" ]] || { echo "FAIL: sub-step already done on return — not backgrounded"; exit 1; }
# the backgrounded child must still complete the work
for _ in $(seq 1 20); do [[ -e "$det/ran-72-run-episodic-maintain.sh" ]] && break; sleep 0.5; done
[[ -e "$det/ran-73-aggregate-metrics.sh" && -e "$det/ran-72-run-episodic-maintain.sh" ]] \
  || { echo "FAIL: detached sub-steps never completed in background"; exit 1; }

echo "PASS test_session_flush"
