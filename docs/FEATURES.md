# nervepack — feature guide (purpose · workflow · example)

> **What this is.** The illuminated tour of every nervepack feature: *why* it
> exists, *how* it's enforced (the workflow and wiring), the *assets* that
> implement it, and a *situational example* of the flow in action. It is the
> companion to the two other top docs:
>
> - **`ARCHITECTURE.md`**, the cheap map (catalog ↔ toggle ↔ code ↔ doc, wiring
>   tables, invariants, the "touch X → check Y" change-impact). Read it before
>   editing code.
> - **`CLAUDE.md`**, the protocol (auth, commits, language policy, directory
>   contract). Read it before doing anything in the repo.
>
> This file answers "what does each layer *do* and *why*"; ARCHITECTURE answers
> "what will my change break"; CLAUDE answers "how do I operate here."

## How the layers fit (the one-paragraph model)

nervepack is a versioned hub of skills, rules, memory, and dev-env setup that
follows you across machines, **delivered into each AI session as user skills** and
**wired into the session lifecycle by hooks + crons**. Knowledge lives in layers
in strict authority order. **`skills > sources > wiki > lessons > episodic`**.
Human-reviewed, curated knowledge (skills) always wins; auto-distilled,
review-waived layers (lessons, episodic) are lower-authority and reversible. A
lesson's `provenance` (`failure` or `success`) and its optional `enforce` block
are independent — either provenance may or may not carry enforcement. Two
data pipelines feed the auto layers: a **capture** pipeline (what we did → episodic,
lessons) and a **performance** pipeline (how much nervepack helped →
metrics → dashboard). Everything is toggle-gated and fails open.

---

# Part 1 — The knowledge layers

The five places knowledge lives, in authority order, plus the lifecycle that moves a
proven pattern *up* the stack into a skill.

## Skills — curated behavioral guidance ("how to act")

**Purpose.** The highest-authority, human-reviewed layer. Rules, conventions, and
domain how-to that you want to load into *every* session. Tiered by namespace:
`np-core-` (cognition machinery), `np-kb-` (knowledge), `np-env-` (environment),
`np-flow-` (workflows). The **engine ships only the machinery tiers** (`np-core-` +
`np-flow-merge-gate`); the `np-kb-`/`np-env-` domain skills are **content** — they live
in your content overlay (or a starter), not the public engine (PR #89), and
`30-link-skills.sh` merges both at link time.

**Workflow.** `skills/<name>/SKILL.md` carries frontmatter (`name` + `description`)
and a lean body. `30-link-skills.sh` symlinks each into `~/.claude/skills/` (the
delivery mechanism) and regenerates `INDEX.md`. Descriptions load passively into the
catalog; the SessionStart directive is the forcing function that makes sessions
actually *invoke* them.

**Assets.** `skills/`, `30-link-skills.sh`, `60-generate-index.sh`, `INDEX.md`,
`.claude-plugin/plugin.json`. Toggle: `skills`.

**Situational example.** You decide a project's buttons should use the warm-light
token set. Instead of re-picking colors, the SessionStart directive routes you to
`np-kb-branding`; you invoke it, get the canonical tokens, and apply them. The
decision was made once and now rides every session.

## Sources — curated technical reference ("what we know")

**Purpose.** Durable, version-pinned reference docs (language books, RFCs, API
surfaces) you consult repeatedly and want to annotate. The defer-first layer:
answer from a pinned source before reaching for model knowledge or live docs.

**Workflow.** Ingested via the protocol in CLAUDE.md (with a soft cap of 100 / hard
300 and a rotate-vs-add prompt). Each `wiki/topics/<topic>/<name>.md` has frontmatter
pinning version + scope, co-located with its synthesis page. Lives in the **content
overlay**, not the engine. (Sources are a conceptual layer that physically resides
*inside* the wiki layer — there is no separate top-level `sources/` dir.)

**Assets.** `wiki/topics/<topic>/` + `wiki/concepts/<concept>/` (overlay), the ingest protocol (CLAUDE.md), `log.md`.

**Situational example.** A question about a specific Rust borrow-checker rule recurs.
Rather than re-deriving it or hitting live docs each time, you ingest the relevant
chapter to `wiki/topics/rust/`, pin the edition, and every future answer cites it. The
topic's synthesis page builds on it too.

## Wiki — LLM-owned synthesis ("connect what we know")

**Purpose.** Entity/concept pages that cross-link skills and sources into a synthesis
the raw layers don't provide. Karpathy's LLM-wiki pattern.

**Workflow.** `wiki/topics/<topic>/<topic>.md` and `wiki/concepts/<concept>/<concept>.md`
synthesis pages regenerate when a cross-linked source or skill changes materially, or
when the lint pass flags staleness. Overlay-resident, LLM-maintained.

**Assets.** `wiki/` (overlay), the lint operation (CLAUDE.md).

**Situational example.** You have a `wiki/topics/aws/` source doc and an
`np-env-secrets-refresh` skill. The `wiki/topics/aws/aws.md` synthesis page ties them
together so "how do I get AWS creds here" lands one page that points at both.

## Episodic memory — auto working memory ("what we did / where we left off")

**Purpose.** The lowest-authority layer: narrative record of what was worked on,
themed by topic. Second-class by design (may be stale, prunable, never holds durable
rules).

**Workflow.** *Capture* (best-effort `SessionEnd`/`PreCompact` Haiku summary →
local inbox) and the **back-capture sweep** (the reliable `SessionStart` trigger)
write notes; the daily `episodic-maintain` cron drains them into `memory/episodic/<topic>.md`
and auto-commits (the one subtree exempt from the human-review gate). *Recall*
injects matching themes on a session's first prompts.

**Assets.** `episodic-capture.sh`, `engine/nervepack_engine/hooks/episodic_recall.py`
(Python port via `cli.py` dispatcher; installed by `52-install-episodic-hooks.sh`), `episodic-match.sh`,
`np-backcapture-sweep.sh`, `agents/np-flow-episodic-maintain.md`, `memory/episodic/` (overlay).
Toggle: `memory`.

**Situational example.** You spend a session migrating a box's network to a new
subnet but don't finish. Next week you ask "where did we leave the eero migration?" and
recall surfaces the episodic theme with the new IPs and where things stood, instead of
you reconstructing it from scratch. (For the *exact* deterministic state of the
session you were just in — branch@head, SDD ledger, last typed instruction — see
**Resume pointer**, next.)

## Resume pointer — deterministic where-we-left-off ("resume from exactly this branch/commit/instruction")

**Purpose.** Episodic memory (above) surfaces *topical themes* — narrative,
summarized, may be stale. The resume pointer is the opposite: an exact,
**deterministic** (no LLM) snapshot of literally the immediately-preceding
session's state — git branch/head/dirty, the SDD ledger/plan in flight, and the
last genuinely-typed instruction — so a fresh session can offer to pick up
precisely where the last one stopped instead of reconstructing state from
scratch or from a fuzzy summary.

**Workflow — three triggers write/refresh the pointer, one surfaces it (all
three are Python, dispatched via `engine/nervepack_engine/cli.py`):**
1. **`SessionStart`** — `cli.py hook resume-sessionstart` (backgrounded, `&`;
   `engine/nervepack_engine/hooks/resume_sessionstart.py`): the reliable
   trigger (invariant 12). On every new session it scans
   `~/.claude/projects/*/*.jsonl` newest-first, skips the current session and
   any `agent-*` subagent transcript, skips anything not yet settled (mtime
   younger than 120s), and reconstructs the pointer from the first survivor —
   the most-recent **completed prior session** — via `resume_write.py`
   (always a fresh write, no `--throttle`). This is the backstop for whatever
   the live writer below missed on that session's final tick.
2. **`UserPromptSubmit`** — `cli.py hook resume-recall`
   (`engine/nervepack_engine/hooks/resume_recall.py`). On a session's first
   prompt (deduped via a marker file so it fires at most once per session): if
   the on-disk pointer belongs to a **different** session and is younger than
   `resume.max_age` (default 86400s = 24h), it emits **one**
   `additionalContext` offer naming the prior branch@head (flagging dirty),
   the SDD ledger/plan if present, and the last typed instruction — surfacing
   BEFORE writing so it never compares the pointer against itself. It then
   (always) writes/refreshes the **current** session's pointer via
   `resume_write.py`'s `--throttle` mode, gated by `resume.interval` (default
   300s).
3. **Opt-in cron** (`resume.cron`, default `off`) — `70-install-memory-cron.sh`
   installs `cli.py resume-write --active --throttle` every `resume.cron_min`
   minutes (default 5) when enabled — its own top-level dispatch branch (not a
   `hook` subcommand, since the writer isn't in `_HOOKS` and the cron has no
   stdin/hook payload to source `--session`/`--transcript`/`--cwd` from).
   `--active` discovers the current session as the newest non-`agent-*`
   transcript, bounded by `resume.active_window` (default 900s) so a stale
   sole transcript never resets the staleness gate.

**The pointer** (`~/.cache/nervepack/resume-pointer.json`, written atomically —
tmp file + `mv`):
```
{schema_version, session_id, ts, cwd, git_branch, git_head, git_dirty,
 transcript_path, last_user_instruction, sdd_ledger, sdd_plan}
```
`git_*` fields come from `git -C <cwd>` and are empty/`false` when `cwd` isn't a
git work-tree (`git_head` is the short SHA). `last_user_instruction` is
`np-transcript-extract.py --last-user` — the last **genuinely typed** message
(gated on `promptSource=="typed"`), empty on any failure. `sdd_ledger` is
`<repo-root>/.superpowers/sdd/progress.md` if it exists; `sdd_plan` is the value
after that ledger's `Plan:` line, if present.

**Assets.** `engine/nervepack_engine/hooks/resume_write.py` (writer, no LLM calls;
dispatched as `cli.py resume-write`), `engine/nervepack_engine/hooks/resume_sessionstart.py`
(`cli.py hook resume-sessionstart`), `engine/nervepack_engine/hooks/resume_recall.py`
(`cli.py hook resume-recall`), `np-transcript-extract.py --last-user`,
`61-install-resume-hook.sh`. Toggle: `resume` (params: `interval=300`,
`max_age=86400`, `cron=off`, `cron_min=5`, `active_window=900`). **Doctor:** the
`resume-pointer` capability checks `resume_write.py` exists and both hooks are
registered in `settings.json` (recognizing either the legacy bash commands or
the new `cli.py` dispatch), else `WARN`s to run `61-install-resume-hook.sh`.

**Situational example.** You're mid-way through Task 4 of an SDD plan on
`feat/resume-pointer-wiring`, several files dirty, when the session dies —
context limit, a closed terminal, a crash. Nothing was committed and no episodic
summary ran. The next session's `SessionStart` reconstructs the pointer from
that now-complete transcript; your very first prompt gets an
`additionalContext` offer: *"A prior nervepack session (~40m ago) was working in
feat/resume-pointer-wiring@a1b2c3d (dirty) — implement Task 4's throttled
writer. Resume from the SDD ledger (.superpowers/sdd/progress.md) / plan
resume-pointer / the branch, or start fresh."* You say "resume" and are back on
the exact branch, head, and task — no re-deriving state from a stale summary.

## Open artifact on write — auto-open a spec/plan doc so a human reads it

**Purpose.** `superpowers:brainstorming` writes specs to
`docs/superpowers/specs/*.md`; `superpowers:writing-plans` writes plans to
`docs/superpowers/plans/*.md`. Both exist to be read and approved by the human
before implementation proceeds, but a chat line saying "written to ..." is
easy to skim past. This feature closes that gap deterministically: the moment
either file is created, it's opened with the OS default handler so attention
actually lands on it.

**Workflow.** A single `PostToolUse` hook, matcher `Write`:
`cli.py hook open-artifact` → `engine/nervepack_engine/hooks/open_artifact.py`.
It checks the written `file_path` against `docs/superpowers/(specs|plans)/*.md`
(matched against the resolved absolute path, so it works whether the tool
reported an absolute or cwd-relative path); a non-matching write, a non-`Write`
tool, or a missing file on disk are all silent no-ops. On a match it calls
`np_dashboard.resolve_opener()` (the same `xdg-open`/`open` resolution the
dashboard hook uses — a local file path opens just as well as a URL) and shells
out to it. Fires only on creation (`Write`), not every subsequent `Edit` — the
ask is "when a plan or spec is *made*", not on every revision.

**Assets.** `engine/nervepack_engine/hooks/open_artifact.py`,
`63-install-open-artifact-hook.sh`. Toggle: `focus` (no params). No dedicated
doctor capability — the generic hook-registration check already covers "is
this wired".

**Situational example.** You ask for a new feature; the session runs
`superpowers:brainstorming`, writes
`docs/superpowers/specs/2026-07-21-thing-design.md`, and — before it even
finishes typing the "spec written, please review" message — the file pops
open in your editor/default `.md` handler, already in focus. You read it right
there instead of trusting a chat summary.

## Lessons — auto-distilled, provenance-tagged, optionally enforced ("in situation X, do/avoid Y — or the approach that worked is Z")

**Purpose.** Auto-distilled patterns from past sessions, both failure→recovery and
proven successes. Above episodic, below skills. Each entry carries a `provenance`
tag (`failure` or `success`) that shapes how it's framed on recall, and *independently*
may carry an optional `enforce` block. Enforcement — gating or injecting right at the
tool call — is the one capability a passive skill structurally cannot fill; it isn't
tied to provenance, so a failure lesson can be advisory-only and a proven success can
be worth enforcing.

**Workflow.** Capture emits two signals: `struggles[]` on sessions with real failures
and `strategies[]` on sessions with wins. `episodic-maintain` distills both into
`memory/lessons/<topic>.md`, tagging each entry `provenance: failure` or
`provenance: success` and adding an `enforce` block only when a tool-call gate is
warranted. `lesson_guard.py` (`PreToolUse`, dispatched via `cli.py hook lesson-guard`)
gates `ask` entries / injects `warn` ones at the tool call for any entry that carries
a non-empty `enforce.tool_match` — skipping advisory entries regardless of provenance.
`lesson_recall.py` (`UserPromptSubmit`, dispatched via `cli.py hook lesson-recall`,
the merge of the former `playbook-recall.sh` + `strategy-recall.sh`) injects
topic-matched entries on a session's first prompts, framing by provenance:
imperative "avoid X" wording for `failure`, advisory "the approach that worked is
Y" wording for `success`.

**Assets.** `engine/nervepack_engine/hooks/lesson_recall.py`,
`engine/nervepack_engine/hooks/lesson_guard.py` (both Python ports via `cli.py`
dispatcher), `agents/np-flow-episodic-maintain.md`, `memory/lessons/` (overlay).
Toggle: `lessons` (param `lessons.enforce`, default on, disables the guard while
advisory recall stays on).

**Situational example.** You once combined `git grep` short flags (`-lin`) and got
silently wrong results. That failure distilled into a `provenance: failure`
`safe-git-grep` lesson with an `enforce` block; now when a prompt mentions git-grep,
the recall hook injects "use long-form flags" *before* you make the same mistake
again, no skill invocation required. Separately, across several sessions you find
that searching GitHub issues surfaces tool limitations faster than official docs —
that becomes a `provenance: success` `github-issue-research` lesson with no `enforce`
block; next time a tool misbehaves, the recall hook reminds you (advisory-only) to
search issues first.

## Graduation — the lifecycle that promotes patterns into skills

**Purpose.** Lessons are a **staging pool**, not a permanent home. A pattern that
keeps proving itself (high `seen`) or outgrows what a skill body may even be (bytes
over the skill budget) is overdue to become a curated, human-reviewed skill. Without
a trigger, entries accrete forever. That is exactly how the `security-review` lesson
grew to 8 KB.

**Workflow.** The daily `nervepack cron skill-maintain` (`np_skill_maintain.py`) runs `np_graduation_detect.py`
(deterministic, no LLM) over the overlay's `memory/lessons/` (its candidate `kind` is
the lesson's `provenance`). Any entry with `seen ≥ graduate_seen` (default 10) or
`bytes > graduate_kb` (default 6 KB) that isn't already `graduated`/`promoted`/`archived`
is **surfaced** to the maintain log and a `graduation-candidates` marker, never
auto-promoted (skills keep the human-review gate). You then graduate it by hand via
`np-core-contribute`: distill the method into a `skills/np-*` skill and flip the
source's `status: graduated`.

**Assets.** `np_graduation_detect.py`, `np_skill_maintain.py` (dispatched via `cli.py cron skill-maintain`),
`tests/skills/test_graduation_detect.py`. Toggle params: `skills.graduate_seen`,
`skills.graduate_kb`. **Surfaced on the dashboard:** `np_skill_maintain.py` also writes
a committed, content-routed `graduation-candidates.json`; `build.py` `load_graduation()`
emits `window.GRADUATION` and `index.html` renders a Graduation-candidates panel
(fail-open empty state). Keeps the engine PII-clean. The data lives in the overlay.

**Situational example.** `security-review` reaches `seen: 30` and 8 KB. The daily
routine flags it in the marker file **and the dashboard's Graduation panel**. You run
the graduation: a lean `np-kb-security-review` skill is born (method in the body, depth
in `references/`), the lesson is marked `graduated`, and the detector stops flagging
it, while `subagent-development` (seen 12) surfaces as the next candidate.

---

# Part 2 — The capture & performance machinery

The two pipelines that feed the auto layers, and the tools that surface and act on
what they learn. Both share one shape: *a cheap hook captures → a local inbox → the
on-exit flush promotes it to a committed layer → a reader surfaces it.* Crons are an
idempotent backup.

## Episodic capture + back-capture sweep

**Purpose.** Get a faithful, cheap record of each session into the pipeline. The
catch: `SessionEnd` is unreliable (Claude Code kills slow `claude -p` hooks; `/exit`
doesn't fire it at all), so the reliable trigger is `SessionStart`.

**Workflow.** `SessionEnd`/`PreCompact` capture is best-effort (Haiku summary → inbox).
The guaranteed path is `engine/nervepack_engine/hooks/backcapture_sweep.py` (dispatched
via `cli.py hook backcapture-sweep`) on `SessionStart` (backgrounded):
it re-runs capture + evaluator against the *previous* session's now-complete on-disk
transcript, deduped per `session_id`.

**Assets.** `engine/nervepack_engine/hooks/episodic_capture.py` (Python port; dispatched
as `cli.py hook episodic-capture <mode>`, backed by `np_capture.py`),
`engine/nervepack_engine/hooks/backcapture_sweep.py`,
`np-transcript-extract.py`. Toggle: `memory` (`memory.backcapture`).

**Situational example.** You finish a session and type `/exit`. No SessionEnd fires.
Nothing is lost: when you next start a session, the back-capture sweep finds that
completed transcript, summarizes it, and scores it, so the work still reaches episodic
+ metrics.

## Performance evaluator + signals

**Purpose.** Quantify how much nervepack actually helped a session, so the system can
be measured and improved instead of assumed-useful.

**Workflow.** At `SessionEnd` (and via the sweep), `np-eval-signals.py` extracts
deterministic signals (skills invoked, `playbook_fires`/`playbook_heeded` — the
enforced-lesson field names, kept as-is across the layer merge — recall injections,
directive present, struggles, tokens) from fire-time markers the hooks dropped, then
a Haiku verdict adds score + helped/shortfalls/suggestions. Records land in a local
inbox.

**Assets.** `engine/nervepack_engine/hooks/evaluator.py` (Python port; dispatched as
`cli.py hook evaluator`, backed by `np_evaluator.py`), `np-eval-signals.py`. Toggle: `evaluator`.

**Situational example.** A session where you invoked three skills and heeded an
enforced lesson scores higher on "nervepack helped" than one where the directive was
present but no skill fired. The low-help session generates a suggestion you can act
on later.

**Signal field reference.** `signals{}` in the metrics record (shape pinned in
`docs/ARCHITECTURE.md` "Record shapes") is produced **deterministically** by
`np-eval-signals.py` — no LLM, no guessing. Each field's zero-bias is documented
here so a dashboard panel reading zero isn't mistaken for a wiring gap:

| Field | Source | Zero-bias note |
|---|---|---|
| `skills_invoked[]` | regex over the transcript JSONL for Skill-tool calls | Legitimately empty if no skills were invoked — not a pipeline gap |
| `playbook_fires` | `lesson-guard` markers in the session-signals log | Genuinely sparse today — only lessons carrying an enforcing `tool_match` fire it; rises naturally as the enforcing-lesson catalog grows |
| `playbook_heeded` | gated-command fingerprints minus fingerprints that were executed anyway | Inherits `playbook_fires` sparseness; also 0 if a gated command ran despite the guard |
| `recall_injections` | `lesson-recall`/`episodic-recall` markers in the session-signals log | **Structural zero for back-captured sessions** — the ephemeral signal log for the original session is gone by the time the back-capture sweep re-scores it, even when recall fired live |
| `directive_present` | `np_enabled directive` at evaluation time | Always populated; reflects the toggle state, not session behavior |
| `directive_tokens` | byte length ÷ 4 of `nervepack-session-directive.md` | Fixed at evaluation time (~730 tokens at current size), not session-specific — the injection-cost side of invariant 11 |
| `struggles` | `struggles[]` length from the matching episodic-inbox record | 0 either because SessionEnd/capture didn't fire for this session, or because it was genuinely clean — not dead code |
| `tool_calls` | count of `tool_use` lines in the transcript | 0 for pure-text automation runs (crons, episodic-maintain) |
| `tokens{input,output,cache_read,cache_creation,total}` | `usage` blocks from assistant turns, deduped by message id | Near-zero for cron/automation sessions; `cache_read` dominates real interactive sessions |

**LLM-derived fields** (top-level on the record, not inside `signals{}`, from the
Haiku verdict): `contribution_score` (int 0-100), `helped[]`, `shortfalls[]`,
`suggestions[]` (`{text, confidence, target, auto_safe}`), `assets_used[]`
(`{asset, kind, used}`). A deterministic cost-aware suggestion is appended by the
evaluator shell itself — independent of the Haiku call — when
`tokens.output >= evaluator.cost_hi_tokens` (default 200k) AND
`contribution_score <= evaluator.score_lo` (default 40).

## Metrics aggregation + dashboard

**Purpose.** Turn the per-session records into a committed time series and a visual
read on trends, wins, and struggles.

**Workflow.** The on-exit flush (`cli.py hook session-flush`) promotes the inbox; the daily
`cli.py cron aggregate-metrics` (backed by `engine/setup/np_aggregate.py`) drains records
into committed `dashboard/data/metrics.jsonl`;
`build.py` renders `metrics.js` for `dashboard/index.html`. The `cli.py hook
open-dashboard` SessionStart hook (`engine/nervepack_engine/hooks/open_dashboard.py`,
backed by `engine/setup/np_dashboard.py`) opens it once per boot (guarded against
the reconnect loop).

**Wiki navigation (left sidebar).** The same `build.py` pass also emits `window.WIKI`
into `metrics.js` (a grouped, searchable index of the overlay's `wiki/topics/<topic>/`
and `wiki/concepts/<concept>/` synthesis pages with their co-located sources, fields `{name, kind, last_updated, sources[], excerpt, html, topic}`).
`index.html` renders it as a grouped/collapsible left sidebar (entities / concepts /
sources-by-topic) with a client-side search filter; clicking an entry opens the
build-rendered HTML page in a new tab; Markdown stays the source (invariant 14).
`build.py` `md_to_html`/`render_pages` writes `data/wiki/{topics,concepts}/*.html` into the
content overlay at build time (content-resident & gitignored). Param-gated by
`evaluator.wiki_nav` (default on); off OR no `wiki/` dir → empty index, the sidebar
shows its empty state (fail-open). Mermaid diagrams in wiki pages render client-side
via the vendored `dashboard/vendor/mermaid.min.js` (loaded only on pages that contain
a diagram — the dashboard's no-external-fetch invariant holds), gated by
`evaluator.wiki_mermaid` (default on). The wiki **data stays in the content overlay**
(`metrics.js`); the engine carries only the build + render code.

**Assets.** `engine/setup/np_aggregate.py` (dispatched via `cli.py cron aggregate-metrics`),
`dashboard/build.py` (`wiki_index()`),
`dashboard/index.html`, `dashboard/vendor/mermaid.min.js`,
`engine/nervepack_engine/hooks/open_dashboard.py` (dispatched as `cli.py hook
open-dashboard`, backed by `engine/setup/np_dashboard.py`),
`open-dashboard.sh`, `np-core-dashboard`.
Toggle: `evaluator` (`dashboard_open`, `dashboard_serve`, `dashboard_port`, `wiki_nav`,
`wiki_mermaid`, `dashboard_sessions`).

**Situational example.** Over a fortnight the dashboard's struggles panel keeps showing
"skill not invoked" (a signal the directive routing needs a new row), visible as a
trend rather than a one-off annoyance.

## Suggestions review + implement/reject

**Purpose.** Close the loop: the evaluator's accumulated suggestions get triaged,
and the good ones can be built by an agent without leaving the dashboard.

**Workflow.** `np-suggestions-review.py` ranks/clears suggestions (the served
dashboard exposes it as buttons via the localhost-only `np-dashboard-server.py`).
Per-row **Implement** spawns an async agentic job (`np-implement-suggestion.sh`) in an
isolated git worktree off the committed base, in `pr` or `direct` mode; **Reject**
resolves it. `np-core-suggestions-review` drives the same flow from any host.

**Assets.** `np-suggestions-review.py`, `np-dashboard-server.py`,
`np-implement-suggestion.sh`, `agents/np-flow-implement-suggestion.md`,
`np-core-suggestions-review`. Toggle: `evaluator` (`implement`, `implement_mode`).

**Situational example.** The Suggestions panel has filled up over a dozen sessions.
You run `/np-suggestions`, it ranks them, you pick three worth building, hit Implement,
and each runs as a worktree-isolated agent that opens a PR, your working tree
untouched.

## Skill maintenance (auto-split) + graduation detection

**Purpose.** Keep skill bodies within budget so the always-loaded catalog doesn't
bloat the context window, and (see Graduation) flag overdue promotions.

**Workflow.** Daily `nervepack cron skill-maintain` (`np_skill_maintain.py`): a deterministic detector
(`np_skill_budget.py`) flags any SKILL.md over the hard `split_kb` (8 KB); only then
does a gated Sonnet pass move overflow into `references/`, validated-or-reverted by
`np_skill_validate.py`. The same routine runs the graduation detector and the
ARCHITECTURE freshness check (both advisory).

**Assets.** `np_skill_maintain.py` (dispatched via `cli.py cron skill-maintain`), `np_skill_budget.py`, `np_skill_validate.py`,
`np_graduation_detect.py`, `np-architecture-freshness.sh` (retained bash advisory subprocess),
`agents/np-flow-skill-maintain.md`. Toggle: `skills` (`split_kb`, `soft_kb`,
`catalog_tok`, `max_per_run`, `graduate_seen`, `graduate_kb`).

**Situational example.** You append three verbose rules to a skill and it crosses 8 KB.
That night the routine detects it, moves the long detail into `references/`, leaves
one-line pointers in the body, validates the frontmatter + links survived, and commits
the split. The body is lean again without you touching it.

---

# Part 3 — Session wiring & control

How nervepack injects itself into a session, stays in sync, and stays controllable.

## Session directive — the forcing function

**Purpose.** Skill *descriptions* load passively, but a passive list gets ignored.
The directive is what makes sessions actually consult nervepack before working from
first principles.

**Workflow.** A synchronous `SessionStart` hook injects `nervepack-session-directive.md`
as context: process expectations (explore → test-first → root-cause → plan), the
domain defaults, and a trigger→skill routing table. It's a **byte-stable prefix**
(no timestamps) so the KV-cache survives; variable context is injected later via
`UserPromptSubmit`.

**Assets.** `engine/nervepack_engine/hooks/session_directive.py` (dispatched as
`cli.py hook session-directive`), `engine/setup/nervepack-session-directive.md`,
`51-install-nervepack-directive-hook.sh`. Toggle: `directive`.

**Situational example.** You open a session and ask to "build a settings page." The
directive has already told you to brainstorm first and to check `np-kb-branding` for
any UI decision, so you reach for both instead of inventing a layout and a palette.

## Cross-machine sync

**Purpose.** A fresh box and a year-old box behave like the same collaborator.

**Workflow.** Sync runs primarily on `SessionEnd`; the `SessionStart` sync is a
throttled backup (`sync.interval`, default 1 day). Strict-safe: fast-forward only,
never auto-rebase or autostash. `np-core-sync` does it on demand.

**Assets.** `40-sync-nervepack.sh`, `np-core-sync`. Toggle: `sync`.

**Situational example.** A cron pushed a new skill from your laptop overnight. You sit
down at the desktop, start a session, and the SessionStart backup sync fast-forwards
it in. The new skill is live without a manual pull.

## Feature toggles

**Purpose.** Every feature has an on/off switch (and tunable params), so nothing is
load-bearing-without-escape and new behavior is always reversible.

**Workflow.** `toggles.conf` (committed) is the manifest; `np-toggle-lib.sh` resolves
`toggles.local → toggles.conf → default-on` (fail-open: unknown = on). Every runtime
check goes through `np_enabled`/`np_param`. A flag needing its own default is a *param*,
not a sub-toggle (sub-toggles wrongly inherit an "on" parent).

**Dashboard panel.** The served dashboard renders a Feature Toggles panel: switches
for bare features and schema-typed inputs for params (types/validation from
`toggle-schema.json` via `np_toggle_schema.py`), with hover help per row.
`np-dashboard-server.py` exposes `GET /api/toggles` + `POST /api/toggle` — bare-feature
flips shell out to `nervepack-toggle.sh` (shared scope commits+pushes; local/managed
stays local, after a confirm dialog for shared flips), dotted params write locally via
`np_toggle.set_local()`. A self-lockout guard refuses to flip `evaluator` or the
panel's own gating params (`dashboard_open`/`dashboard_serve`/`toggle_ui`). Gated by
`evaluator.toggle_ui` (default on).

**Assets.** `toggles.conf`, `np-toggle-lib.sh`, `nervepack-toggle.sh`, `np-core-toggle`,
`toggle-schema.json`, `np_toggle_schema.py`, `np-dashboard-server.py` (`/api/toggles`).

**Situational example.** Lesson enforcement is too aggressive on a given machine. You
run `np-core-toggle` → set `lessons.enforce` off locally; the guard hook no-ops there
while advisory recall and the rest of the fleet keep working.

## Memory-store promotion

**Purpose.** Durable facts that landed in the session-scoped local memory store should
be promoted into a real skill, not stranded.

**Workflow.** A local cron (daily 08:00) runs `np-flow-memory-promote.md`: triage the
memory store, promote durable entries into the right skill, drop stale ones, commit +
push. Local-only because the cloud can't reach the memory dir.

**Assets.** `engine/setup/np_agentic_cron.py` (Python port; `memory_promote()`,
dispatched via `cli.py cron memory-promote`), `agents/np-flow-memory-promote.md`.
Toggle: `memory.promote`.

**Situational example.** You told a session to "remember" a new AWS profile name and it
went to local memory. The next morning's cron recognizes it as durable and folds it
into `np-env-secrets-refresh`, so every machine inherits it.

## Struggle escalation + skill-trigger recall

**Purpose.** Catch a session that's visibly struggling (or about to skip a skill) and
nudge it mid-flight, not just at the next session.

**Workflow.** `struggle-escalation` (Python port via `cli.py` dispatcher, `UserPromptSubmit`,
once/session) fires when the lesson guard has tripped enough times after enough prompts,
injecting a skill-applicability reminder. `skill-trigger-recall` (Python port via `cli.py`
dispatcher) matches skill-authoring prompt patterns and reminds you to follow a disciplined
skill-authoring process first (naming a host skill such as `superpowers:writing-skills`
only as an optional example).

**Assets.** `engine/nervepack_engine/hooks/struggle_escalation.py`,
`engine/nervepack_engine/hooks/skill_trigger_recall.py`,
`57-install-escalation-hook.sh`, `59-install-skill-trigger-hook.sh`, their installers.
Toggles: `evaluator.escalation`, `skills.trigger_recall`.

**Situational example.** Three tool calls into a task you keep tripping the lesson
guard. Escalation fires once ("you've struggled twice, is there a skill for this?")
and you stop to invoke the one you'd been bypassing.

---

# Part 4 — Distribution, portability & safety

The machinery that lets nervepack run beyond one Claude Code box and stay safe to
publish.

## MCP layer

**Purpose.** Expose nervepack's surface to any MCP-capable host as tools, so the
modpack is model-agnostic.

**Workflow.** `np-mcp-server.py` (stdlib stdio JSON-RPC) dispatches to the wrapped
scripts (doctor, episodic-match, toggle, dashboard build, capture/contribute). Writes
are gated (`mcp.writes`, `mcp.contribute`).

**Assets.** `np-mcp-server.py`, `engine/bin/nervepack-mcp`, `58-install-mcp.sh`.
Toggle: `mcp`.

**Situational example.** From a non-Claude host you call the `nervepack_recall` tool
over MCP and get the same episodic themes a Claude Code `/recall` would surface.

## LLM-agnostic onboarding

**Purpose.** Let any agentic host (Goose, OpenHands, Cline, Continue) wire nervepack
itself by reading a tool-neutral contract, and let any model back the automation.

**Workflow.** `np-llm.sh` is the backend-neutral LLM-CLI seam (sets `NERVEPACK_AGENT=1`,
swaps `claude` for any OpenAI-compatible endpoint). `np-core-onboard` reads
`engine/onboard/ONBOARD.md`, wires the host, and proves it with `np-doctor.sh`. Pre-
flight gates check the *backend*, not the `claude` binary.

**Assets.** `np-llm.sh`, `engine/onboard/`, `np-doctor.sh`, `np-core-onboard`.

**Situational example.** On a Goose box with a local model, `/np-onboard` writes the
adapter, points the seam at the local endpoint, and the doctor reports PASS. The
capture/evaluator crons run on the local model with no Claude binary present.

## Engine / content split + the content seam

**Purpose.** Keep the engine public and shareable while personal content stays
private, and one resolver points every consumer at the right tree.

**Workflow.** The engine repo holds machinery + generic skills; the overlay
(`NP_CONTENT_DIR`) holds wiki (with co-located sources) / memory (episodic+lessons) / metrics + personal
skills. `np-content-lib.sh` (`np_content_dir`) resolves the overlay for every consumer;
unset falls back to the engine root (legacy single-repo).

**Assets.** `np-content-lib.sh`, `NP_CONTENT_DIR`, the `nervepack-content-example` repo.

**Situational example.** The graduation detector needs to scan *your* lessons. It
asks `np_content_dir`, gets your overlay path, and scans there. A public clone
with no overlay simply finds nothing and no-ops.

## Team overlay — a shared layer above your personal content

**Purpose.** Let a team share a curated baseline (skills, lessons, wiki) without
giving up private, per-person memory. The engine stays public, your personal
overlay stays yours, and a third overlay carries what the team holds in common.

**Workflow.** Configure a team root with `NP_TEAM_DIR` (or write the path into
`~/.config/nervepack/team-dir`) and the overlay stack becomes `team > personal >
engine`. That value may be a **comma-separated list of up to four team dirs**,
highest-precedence first (`squad,division,org` → `squad > division > org > personal >
engine`), so a nested org can layer shared content; more than four is a hard error and
the session falls back to personal-only (the doctor's `team` check `WARN`s on such an
invalid config rather than hiding it). `np-layer-lib.sh` builds that stack and every
reader scans it highest-first.
Skills are **override-only**, so a team `np-kb-branding` shadows your personal one of
the same name. The topic layers (lessons, episodic, wiki) combine per the
`team.merge` param, `override` (default, team wins on a name clash), `concatenate`
(both sets surface), or `team-only` (ignore personal for that read). **Reads merge,
writes stay personal.** Auto-capture always writes your personal overlay, so nothing
you do bleeds into the shared layer by accident. Publishing to the team is the one
explicit path, `np-core-contribute --layer team` (or "save this to the team layer").
**Metrics stay personal-only by design.** The dashboard merges *learned* counts
(the lessons layer, split by provenance) across both overlays, but your session
scores are never shared. Gated by the `team` toggle, which is dormant until a team
dir resolves. Complete through Phase 3 (recall hooks, wiki index, dashboard
learned-counts, and MCP recall all merge across layers).

**Assets.** `np-layer-lib.sh` (`np_content_layers`/`np_merge_mode`/`np_merge_roots`/
`np_layer_roots`) and its Python mirror `np_content.py` (`merge_roots`/`merge_mode`),
`np_team_dirs`/`np_team_dir` (the comma-list parse/validate/cap
resolver, and its highest-precedence first entry) in `np-content-lib.sh`, the two recall hooks
(`engine/nervepack_engine/hooks/episodic_recall.py`,
`engine/nervepack_engine/hooks/lesson_recall.py` — both Python ports via `cli.py`
dispatcher), `dashboard/build.py` (`wiki_index`,
`learned_counts`), `np-mcp-server.py` (`_tool_recall`), `np-core-contribute`.
Toggle: `team` (`team.merge`).

**Situational example.** Your data team keeps a shared `np-kb-data-team-mcp` skill and
a `safe-migrations` lesson in a team overlay. A new teammate points `team-dir` at it
and inherits both on their first session, while their own half-finished migration notes
stay in their personal episodic memory where only they see them. When they harden a
new rule worth sharing, they run `contribute --layer team` and it lands in the shared
overlay for everyone.

## CI PII guard + publish snapshot

**Purpose.** Make it structurally impossible for personal data to land in the (public-
to-be) engine.

**Workflow.** `np-publish-scan.py` scans for secrets/PII (incl. RFC1918 LAN IPs) with a
vetted false-positive allowlist; the `pii-guard` CI job runs it on every push/PR. The
pre-publish gate (`np-publish-snapshot.sh`) exports a history-free ref, scans it, and
refuses if dirty. It never pushes (public release stays human-gated).

**Assets.** `np-publish-scan.py`, `scan-allowlist.txt`, `np-publish-snapshot.sh`,
`PUBLISH.md`, the `pii-guard` CI job.

**Situational example.** You graduate a lesson into an engine skill but leave a real
hostname in an example. The PII guard fails CI on the push, naming the file and line,
before it can become part of the public engine.

## Permission allowlist & secrets refresh

**Purpose.** Reduce permission prompts for known-safe tool calls (allowlist), and pull
credentials onto a machine without the secret values entering the model context
(secrets refresh).

**Workflow.** The allowlist is a local-scope managed toggle (install/remove paired).
`np-env-secrets-refresh` pulls from Bitwarden and applies to aws-vault / get-secret.sh
out-of-band.

**Assets.** `90/91-…-permissions.sh`, `np-env-secrets-refresh`. Toggle: `allowlist`.

**Situational example.** You ask to "refresh AWS creds." The skill pulls the secret
from Bitwarden and writes the profile with `umask 077` + `chmod 600`. The value
never appears in the transcript or prompt cache.

---

## See also

- **`ARCHITECTURE.md`**, the change-impact map (touch X → check Y), runtime wiring
  tables, design invariants, and the record shapes the readers depend on.
- **`CLAUDE.md`**, directory contract, commit conventions, language/model policy,
  the ingest/lint protocols for sources + wiki.
- **`ROADMAP.md`**, deferred work and the trigger to revisit each item.
- **`INDEX.md`**, the auto-generated skill catalog.
