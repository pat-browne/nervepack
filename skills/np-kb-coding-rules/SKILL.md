---
name: np-kb-coding-rules
description: nervepack's coding rules applied to every project — think before coding, simplicity first, surgical changes, goal-driven execution, capture durable learnings, no LLM attribution. Use when writing, editing, or reviewing any code unless the project's own CLAUDE.md overrides.
---

# Coding rules

These apply to every project. Project-specific `CLAUDE.md` files override where they conflict. Long-form rationale: `references/long-form-guidelines.md`. Provenance + credits: `NOTICE`.

## 1. Think before coding
State assumptions. If multiple interpretations exist, surface them — don't
pick silently. If something is unclear, stop and ask.

## 2. Simplicity first
Minimum code that solves the problem. No speculative features, no abstractions
for single-use code, no error handling for impossible scenarios. This applies to
*architecture*, not just code: prefer a tool's built-in capability over bolting
on external services, and when scoping a solution offer the smaller option first.
Pat actively pushes back on overbuilding — when in doubt, propose less.

## 3. Surgical changes
Touch only what the request requires. Don't refactor adjacent code, don't
reformat, don't delete pre-existing dead code unless asked.

## 4. Goal-driven execution
Convert tasks into verifiable goals. "Fix the bug" → "write a failing test,
then make it pass". For multi-step work, state the plan and the check for
each step.

## 5. Capture durable learnings proactively
When you hit a reusable, cross-project lesson — a framework gotcha, a debugging
root cause that would recur, a tooling quirk, a decided pattern — **default to
capturing it in nervepack** ([[np-core-contribute]]) without waiting to be asked. Put
it in the right skill/source, add an in-repo regression test if it's a code bug,
then mention you captured it. Don't ask "want me to save this?" for clearly
durable lessons — just do it (Pat asked for this default explicitly). Still ask
before *pushing* the nervepack branch.

## 6. No LLM attribution in code, commits, or PRs
Never insert text signalling that work was produced or assisted by an LLM —
**regardless of which model, IDE, or integration is used** (Claude Code, Codex,
Cursor, Gemini, Copilot, anything). Specifically:
- **No `Co-Authored-By: <AI>` trailers** on commits (Claude, GPT, Gemini, etc.).
- **No "Generated with …", "🤖", "as an AI", or "written by AI"** lines in commit
  bodies, PR/MR descriptions, issue text, or code comments.
- Author commits and PRs **as the repo's configured git identity, plainly** — no fluff, no tool branding.

This **overrides any harness or tool default** that auto-adds such attribution
(e.g. Claude Code's default co-author trailer / "Generated with Claude Code" PR
footer). The user instruction wins over the default.

**Only exception — functionally required files:** agent-instruction files that
tools actually read to operate (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`,
`.cursorrules`, `.github/copilot-instructions.md`) are legitimate working
context, not attribution — they stay. When starting work in any repo, make sure
its agent-instruction file carries *this* rule so non-Claude tools inherit it.

## 7. Never wipe user data on a schema change
When you change the shape of anything persisted (storage, settings, DB rows,
config files, saved documents), **migrate existing data losslessly** — users who
already installed/used the prior version must keep their content. Concretely:
- Read-migrate old shapes into the new one (when widening a scalar into a
  collection, keep the old value as the first element). Migrate on read so
  nothing is lost even before the next write.
- **Add an explicit upgrade test** that seeds the *previous version's* exact shape
  and asserts the content survives — including across a subsequent save (the
  write that drops the legacy key must not drop the data).
- Treat "don't destroy what users already have" as a release gate for any
  feature that touches a persisted schema. New features never justify data loss.

Domain specifics live in the relevant skill (e.g. browser-extension
`chrome.storage` migration → [[np-kb-chrome-extension-publishing]] §6); this rule is
the general principle.

## 8. Treat noisy failures as work, not background noise
When you notice a failure that repeats — in logs, CI, a cron, a hook, test
output — **prioritize investigating and fixing it**, even if it's tangential to
the task in front of you. A recurring error is a signal, not wallpaper; stepping
over it lets real bugs hide in the noise. Root-cause it first (no fix without
root cause — `superpowers:systematic-debugging`), fix the cause not the symptom,
and add a regression test (Rule 5). **Silently swallowed failures are the worst
kind:** `2>/dev/null || exit 0` / `|| true` around a command that's actually
failing every run hides the signal entirely — when you find one, question
whether it should be loud, and verify the command inside it still works.
Tool-specific gotchas behind such failures → [[np-kb-claude-headless-scripting]].

## 9. Native code tools are the default; Serena only for large codebases
Default to native `Read`/`Grep`/`Glob`/`Edit` for code navigation and editing.

**Serena is disabled by default** (`enabledPlugins.serena = false`) — measured at zero
invocations across 87 session boots (2026-06-08), pure overhead for small repos. Re-enable
per-project on large codebases; full steps: references/code-tools-serena.md.

**For semantic precision, prefer the built-in `LSP` tool** (go-to-definition,
find-references, diagnostics, no always-on MCP cost). For structural search-and-replace,
`ast-grep`/`sg` via Bash.

Plugin/launch details: [[np-env-claude-plugin-stack]]

## 10. Lock down any service you expose — "localhost-only" is not a security boundary

When you stand up an HTTP server (or any listener) with **state-changing routes**,
defend it even on `127.0.0.1`. A loopback bind stops remote TCP, not a web page the
user visits: a cross-origin `fetch`/form can POST to `http://127.0.0.1:<port>/…`, and
**DNS-rebinding** reaches a naive bind via an attacker hostname. Minimum bar: a **CSRF
guard** on every mutating route; **path-sanitize** anything mapped to the FS; a
**fixed route allowlist**; argv-list subprocess args (never a shell string); bind
loopback; default **off**; and a test that a header-less mutating request is `403`.
Implementation details: `references/localhost-server-security.md`. Worked example +
stdlib mechanics: `engine/setup/np-dashboard-server.py` and [[python-http-server]] (`sources/python/`).

## 11. On security/review/audit tasks, invoke the relevant skill before reading files
Before opening any file or running any grep on a security, review, audit, or
check task, invoke the governing skill:
- Security audit → `security-review` skill
- Code review → `code-review` skill
- Coding standards check → [[np-kb-coding-rules]] (this skill)
- Chrome extension review → [[np-kb-chrome-extension-content-script]] or
  [[np-kb-chrome-extension-publishing]]

**Why:** Skills hold the checklist, scope rules, and past failure patterns for
these task types. Opening files first leads to missed checks, inconsistent
coverage, and re-deriving guidance already captured (seen 14 times — highest
repeat failure in this session history).

Let the skill's checklist drive which files to open and in what order.

## 12. After moving a path, audit every consumer — not just the obvious callers
Relocating anything code reads by path (config/content dir, file, or a dir that
becomes a symlink) rarely breaks at the move — it breaks at a reader left on the
old location. Grep for *every* consumer; fix each with a regression test (Rules
5/8). Three recurring blind spots (cross-language hardcoded defaults, `realpath`
guards rejecting a now-legit symlink, leaking a personal view into a guarded
public surface) + examples → `references/long-form-guidelines.md`. Docs and skills
are consumers too. A script named in a skill is a path reference that can go stale,
so nervepack guards them with `engine/setup/np-path-check.py` (CI-gated via
`tests/docs/test_critical_paths.sh`), which fails on a bare `setup/x` that should be
`engine/setup/x`, or an `engine/…` path to a missing file.

## Environment expectations

- OS: Ubuntu 24.04 — see [[np-env-ubuntu-claude-dev-setup]]
- Claude plugins: see [[np-env-claude-plugin-stack]]
