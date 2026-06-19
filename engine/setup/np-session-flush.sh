#!/usr/bin/env bash
# SessionEnd promotion flush — makes the crons a BACKUP, not the only path.
#
# After the capture + evaluator SessionEnd hooks have written this session into the
# local inboxes, this drains them into the committed layers immediately instead of
# waiting for the daily/weekly cron:
#   1. metrics  : 73-aggregate-metrics.sh  (deterministic, cheap)  evaluator-inbox -> metrics.jsonl -> dashboard
#   2. episodic : 72-run-episodic-maintain (Sonnet agent)          episodic-inbox  -> episodic/<topic>.md
# Both are idempotent (empty inbox = no-op, no empty commit), so the daily/weekly
# crons remain a safe backup if this is ever cut short.
#
# Two load-bearing properties:
#  - RE-ENTRY GUARD: step 2 runs `claude -p`, which re-fires SessionEnd -> this
#    script. Without the NERVEPACK_AGENT bail we recreate the SessionEnd recursion
#    loop (see [[np-kb-claude-headless-scripting]] §7). This bail MUST stay first.
#  - DETACH: the maintain agent takes ~30-60s; we re-exec under setsid and return
#    immediately so session exit is never blocked and the work survives teardown.
set -uo pipefail

# 1. Re-entry guard FIRST — before detaching — so a nested (agent) SessionEnd bails
#    instead of spawning another flush.
[[ -n "${NERVEPACK_AGENT:-}" ]] && exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${SESSION_FLUSH_LOG:-$HOME/.cache/nervepack/session-flush.log}"

# 2. Detach: re-exec ourselves in a new session, return instantly. NP_FLUSH_NODETACH
#    keeps it foreground for tests.
if [[ -z "${NP_FLUSH_DETACHED:-}" && "${NP_FLUSH_NODETACH:-0}" != "1" ]] && command -v setsid >/dev/null 2>&1; then
  NP_FLUSH_DETACHED=1 setsid "$0" "$@" >/dev/null 2>&1 </dev/null &
  exit 0
fi

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
echo "$(date -u +%FT%TZ) flush start" >>"$LOG" 2>&1

# Sequential (not parallel) so the two scripts' commits/pushes don't race. Each
# self-gates on its own toggle (evaluator.aggregate / memory.maintain) and fails open.
"$HERE/73-aggregate-metrics.sh"     >>"$LOG" 2>&1 || true
"$HERE/72-run-episodic-maintain.sh" >>"$LOG" 2>&1 || true

echo "$(date -u +%FT%TZ) flush done" >>"$LOG" 2>&1
exit 0
