# §8 SessionEnd unreliable — GH issues, incident, and fix details

Detail for §8 of [[np-kb-claude-headless-scripting]].

## GitHub issues (verified CLI 2.1.x)

- **`/exit` → SessionEnd never fires** (GH anthropics/claude-code #35892: prints
  "Goodbye!" and exits immediately). **Ctrl+C cancels** SessionEnd (#32712,
  regression in 2.1.72+). Only Ctrl+D / some teardown paths fire it.
- **Even when it fires, the process exits without awaiting slow hooks** (#41577):
  a SessionEnd hook doing a ~15–30 s `claude -p` call is killed before it can
  write its output **or** log a bail — so the symptom is *no record AND no
  bail-log line* (the §2 trace never appears because the kill lands mid-call).

## How this presents (real nervepack incident, June 2026)

episodic-capture + np-evaluator silently captured nothing for weeks. Tell-tale
signature: the *fast* SessionEnd hook (`np-session-flush`, no `claude -p` when
inboxes are empty) logged normally, while the two *slow* `claude -p` hooks left
no log and no inbox record; the committed metrics were all hand-seeded. Don't
chase the script — it runs to completion in ~19 s when invoked manually. The
hook is killed.

## Fix implementation details

Move slow per-session capture to a **backgrounded SessionStart hook** (SessionStart
*is* awaited; work survives because the parent session stays alive):

- A backgrounded SessionStart hook back-captures the *previous* session from its
  now-complete on-disk transcript (`~/.claude/projects/*/*.jsonl`), re-running the
  same capture/evaluator. Idempotent (per-`session_id` claim marker + dedup vs the
  committed record), bounded (recent days, capped count), fail-open. Skip
  `agent-*` transcripts — those are subagent runs, not real sessions. Skip the
  current/active session (filename `session_id`, and a min-age guard since an
  active transcript is still being written). Implemented in
  `setup/np-backcapture-sweep.sh`.
- Keep the SessionEnd hooks as **best-effort** (they help on the paths that do
  complete) but never *depend* on them. Promotion to the committed layer rides the
  on-exit flush **and** the daily/weekly crons — the awaited triggers, not SessionEnd.
- Register SessionStart hooks with a trailing `&` so the sweep never delays startup
  (still cheap + idempotent per §4). Don't background *inside* a SessionEnd hook to
  dodge the kill — `nohup … & disown` there races process teardown; the
  SessionStart sweep is the robust path.
