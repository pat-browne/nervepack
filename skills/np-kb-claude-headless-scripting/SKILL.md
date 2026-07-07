---
name: np-kb-claude-headless-scripting
description: Gotchas for driving the `claude` CLI headlessly (`-p`/`--print`) from shell scripts, hooks, and crons, AND for writing Claude Code lifecycle hooks safely. Pass the prompt via stdin — the variadic `--allowedTools <tools...>` silently eats a trailing positional prompt and aborts the CLI. SessionStart fires repeatedly (startup/resume/clear/compact) so guard GUI/side-effects to once-per-boot or they can loop. Use when writing or debugging any script, SessionStart/SessionEnd/PreCompact/UserPromptSubmit hook, or cron wrapper (nervepack's own episodic capture/maintain/evaluator/recall hooks and the dashboard-launch hook all rely on this).
---

# Driving `claude -p` from scripts, hooks, and crons

Patterns for invoking the `claude` CLI non-interactively (`-p` / `--print`)
from Bash. nervepack's own machinery relies on this — `engine/setup/episodic-capture.sh`,
`72-run-episodic-maintain.sh`, `np-evaluator.sh`, `episodic-recall.sh` — so these
gotchas bite our own hooks.

## 1. Pass the prompt via stdin, never as a trailing positional

**The trap:** `--allowedTools`/`--disallowedTools` take `<tools...>` — a
**variadic** option (commander.js). It greedily consumes *every* following
non-flag argument, including a prompt placed after it:

```bash
# BROKEN — the variadic eats "$prompt" as if it were another tool name:
claude -p --allowedTools Bash Read Write "$prompt"
#   → allowedTools = [Bash, Read, Write, <prompt>], no positional prompt left
#   → Error: Input must be provided either through stdin or as a prompt
#     argument when using --print
```

**The fix — pipe the prompt in on stdin.** Flags then have nothing trailing to
over-consume, and stdin also dodges `ARG_MAX` for large prompts:

```bash
# CORRECT:
printf '%s' "$prompt" | claude -p --allowedTools Bash Read Write
# or, in a wrapper that execs:
exec claude -p --allowedTools Bash Read Write <<<"$prompt" >>"$LOG" 2>&1
```

## 2. Don't let a fail-open hook swallow a real failure silently

Lifecycle hooks (SessionEnd, PreCompact) must exit 0 so they never disrupt the
session — but `raw="$(claude ... 2>/dev/null)" || exit 0` will hide a CLI that
fails on *every* run (exactly the §1 bug — symptom: a hook's output dir gets
`mkdir`'d but stays empty forever). Mitigations:

- Make the invocation correct (§1) so the fail-open path is only hit on genuine
  edge cases, not every run.
- Route every bail through a `bail()` helper that appends a dated one-line reason
  to a log and *then* `exit 0` — failures are discoverable without breaking
  fail-open (implemented in `episodic-capture.sh → episodic-capture.log`).
- This is the concrete case behind [[np-kb-coding-rules]] §8 — a
  silently-swallowed, every-run failure.

## 3. Make script CLI calls testable

Parameterize the binary and any log path so a stub can stand in:

```bash
CLAUDE="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
LOG="${SOMETHING_LOG:-$HOME/.cache/.../x.log}"
```

A stub that merely `printf`s JSON and **ignores argv** will NOT catch the §1
bug. A regression test's stub must model the variadic parsing: read stdin, treat
`--allowedTools` as consuming following args, and error like the real CLI if no
prompt arrived. See `engine/setup/tests/episodic/test_{capture,maintain}_invocation.sh`.

## 4. SessionStart hooks fire repeatedly — never trigger a GUI/side-effect unguarded

SessionStart fires on `startup`, `resume`, `clear`, and `compact`, and a
`"matcher": ""` matches **all** of them. A SessionStart hook that opens a GUI
window under a remote-desktop session can **self-sustain a loop** (~150 sessions
in seconds, ~1.5 s/cycle). Matching only `startup` does **not** fix it — each
reconnect-spawned session is itself a fresh `startup`.

**Fix: guard irreversible/GUI side-effects on the boot id:**

```bash
boot_id="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown)"
m="$HOME/.cache/nervepack/open-boot"
[[ "$(cat "$m" 2>/dev/null)" == "$boot_id" ]] && exit 0
mkdir -p "$(dirname "$m")"; printf '%s' "$boot_id" > "$m"
```

**Diagnose** a loop: `ls -lt ~/.claude/projects/*/*.jsonl` — many files seconds apart. (`engine/setup/74-open-dashboard.sh`.)

## 5. Other flags worth setting in headless runs

- `--model <id>` — pin it; don't inherit an interactive default. Cheap summarizers
  → `claude-haiku-4-5-20251001`; agentic passes → `claude-sonnet-4-6`.
- `--permission-mode bypassPermissions` — for unattended crons that must not block
  on a prompt (only when the allowed-tools set is already constrained).
- `--bare` — suppress hooks/LSP/plugin-sync in headless **agent** runs: §7's marker
  only stops *nervepack's* hooks; third-party plugin hooks still hang a headless agent without it (references/recursion-guard.md).
- Output is plain stdout; strip stray fenced code blocks before `jq` if you asked for JSON.

## 6. Feeding a session transcript to a headless summarizer

Two silent traps (both hit the §2 bail path; symptom: empty output):

- **Don't byte-tail raw JSONL.** Extract readable text with `jq` first, then tail.
  Raw transcripts embed base64 blobs; tailing inside a blob feeds the model garbage.
- **Use `--append-system-prompt`** to recast the model as a non-conversational
  extraction function. `BEGIN/END` delimiters alone are insufficient (verified:
  model continued 2/3 runs without the system-prompt reframe).
- **Cap input**: ~48 KB (capture) / ~32 KB (evaluator). Extractor + capping lives
  in `engine/setup/np-transcript-extract.py`, called by both hooks.

Full jq extractor, system-prompt template, and regression test notes:
references/transcript-extraction.md.

## 7. A hook that calls `claude -p` will recurse — guard against re-entry

**Headless `claude -p` fires the lifecycle hooks too** (verified: a SessionEnd
hook ran for a `claude -p` invocation, and a marker env var propagated into it).
So a hook that *itself* calls `claude -p` re-invokes itself forever.
Loop diagram, incident notes, and regression test: references/recursion-guard.md.

**Fix — one env marker, set by every nervepack `claude -p`, checked by every hook
that calls `claude -p`:**

```bash
# Top of the recursing hook (bare line — no lib dependency, can't fail-open wrong):
[[ -n "${NERVEPACK_AGENT:-}" ]] && exit 0

# Every nervepack `claude -p` marks the agent it spawns:
... | NERVEPACK_AGENT=1 "$CLAUDE" -p ...          # inline (pipe/subshell)
export NERVEPACK_AGENT=1; exec "$CLAUDE" -p ...   # exec form
```

The marker is inherited by `claude -p` and by the hook subprocess it spawns, so
the nested SessionEnd bails at depth 1. Guard the hooks that *call* `claude -p`
(capture, evaluator) — not the cron entry points (they run at top level where the
marker is unset). This is the §2 fail-open trap at its worst — silent recursion.

## 8. SessionEnd is unreliable for slow work — capture on SessionStart instead

**`/exit` doesn't fire SessionEnd at all; even when it fires, slow hooks
(any `claude -p` call) are killed before they complete** (verified CLI 2.1.x).
Symptom: no record AND no bail-log line — the kill lands mid-call, so §2's
trace never appears.

**Fix:** move slow per-session work to a **backgrounded SessionStart hook** —
SessionStart is awaited; the work survives. Keep SessionEnd hooks as
best-effort only; never depend on them. Implemented in
`engine/setup/np-backcapture-sweep.sh`.

GH issues, incident narrative, and implementation details:
references/sessionend-unreliable.md.

## 9. Keep runtime hook/cron scripts macOS/BSD-portable

Runtime hook/cron scripts ship unported on any adopting host, including stock macOS
(BSD coreutils, bash 3.2). Avoid GNU-only constructs that silently break on BSD;
the `NN-*.sh` bootstrappers are *exempt* (Linux/apt-only by design).

Specific patterns, portable replacements, and portability test: references/macos-portability.md.

## Related

- [[np-kb-coding-rules]] §8 (noisy failures) and §5 (regression tests)
- Systematic root-cause debugging — used to find the §1, §6, §7 and §8 bugs
- docs/ARCHITECTURE.md invariant 12 (SessionEnd unreliable; SessionStart is the reliable trigger)
