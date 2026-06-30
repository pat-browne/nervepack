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
in strict authority order. **`skills > sources > wiki > playbooks > episodic`**
(strategies sit beside playbooks as the advisory, success-driven mirror). Human-
reviewed, curated knowledge (skills) always wins; auto-distilled, review-waived
layers (playbooks, strategies, episodic) are lower-authority and reversible. Two
data pipelines feed the auto layers: a **capture** pipeline (what we did → episodic,
playbooks, strategies) and a **performance** pipeline (how much nervepack helped →
metrics → dashboard). Everything is toggle-gated and fails open.

---

# Part 1 — The knowledge layers

The six places knowledge lives, in authority order, plus the lifecycle that moves a
proven pattern *up* the stack into a skill.

## Skills — curated behavioral guidance ("how to act")

**Purpose.** The highest-authority, human-reviewed layer. Rules, conventions, and
domain how-to that you want to load into *every* session. Tiered by namespace:
`np-core-` (cognition machinery), `np-kb-` (knowledge), `np-env-` (environment),
`np-flow-` (workflows).

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

**Assets.** `episodic-capture.sh`, `episodic-recall.sh`, `episodic-match.sh`,
`np-backcapture-sweep.sh`, `agents/np-flow-episodic-maintain.md`, `memory/episodic/` (overlay).
Toggle: `memory`.

**Situational example.** You spend a session migrating a box's network to a new
subnet but don't finish. Next week you ask "where did we leave the eero migration?" and
recall surfaces the episodic theme with the new IPs and the resume point, instead of
you reconstructing it from scratch.

## Playbooks — failure-driven, enforced ("in situation X, do/avoid Y")

**Purpose.** Auto-distilled procedural interventions from past failure→recovery.
Above episodic, below skills. Unique trait: **enforced at the tool call**, not just
advisory. This is the niche a passive skill structurally cannot fill.

**Workflow.** Capture emits `struggles[]` on sessions with real failures →
`episodic-maintain` clusters them into `memory/playbooks/<topic>.md` with an `enforce`
block → `playbook-guard.sh` (`PreToolUse`) gates `ask` playbooks / injects `warn`
ones at the tool call, and `playbook-recall.sh` (`UserPromptSubmit`) injects topic-
matched ones with imperative framing.

**Assets.** `playbook-recall.sh`, `playbook-guard.sh`, `agents/np-flow-episodic-maintain.md`,
`memory/playbooks/` (overlay). Toggle: `playbooks`.

**Situational example.** You once combined `git grep` short flags (`-lin`) and got
silently wrong results. That failure distilled into the `safe-git-grep` playbook; now
when a prompt mentions git-grep, the recall hook injects "use long-form flags" *before*
you make the same mistake again, no skill invocation required.

## Strategies — success-driven, advisory ("when X, the approach that worked is Z")

**Purpose.** The success mirror of playbooks: reusable patterns that worked. Same
second-class status, but **advisory** (injected, never enforced at the tool call).
Their distinct value over a skill is auto-capture + topic-triggered surfacing.

**Workflow.** Capture emits `strategies[]` → `episodic-maintain` distills into
`memory/strategies/<topic>.md` → `strategy-recall.sh` (`UserPromptSubmit`) injects matching
ones as "approaches that worked before."

**Assets.** `strategy-recall.sh`, `agents/np-flow-episodic-maintain.md`,
`memory/strategies/` (overlay). Toggle: `strategies`.

**Situational example.** Across several sessions you find that searching GitHub issues
surfaces tool limitations faster than official docs. That becomes the
`github-issue-research` strategy; next time a tool misbehaves, the recall hook reminds
you to search issues first.

## Graduation — the lifecycle that promotes patterns into skills

**Purpose.** Playbooks and strategies are a **staging pool**, not a permanent home.
A pattern that keeps proving itself (high `seen`) or outgrows what a skill body may
even be (bytes over the skill budget) is overdue to become a curated, human-reviewed
skill. Without a trigger, entries accrete forever. That is exactly how the
`security-review` strategy grew to 8 KB.

**Workflow.** The daily `75-skill-maintain.sh` runs `np-graduation-detect.py`
(deterministic, no LLM) over the overlay's `memory/strategies/` and `memory/playbooks/`. Any entry
with `seen ≥ graduate_seen` (default 10) or `bytes > graduate_kb` (default 6 KB) that
isn't already `graduated`/`promoted`/`archived` is **surfaced** to the maintain log
and a `graduation-candidates` marker, never auto-promoted (skills keep the
human-review gate). You then graduate it by hand via `np-core-contribute`: distill the
method into a `skills/np-*` skill and flip the source's `status: graduated`.

**Assets.** `np-graduation-detect.py`, `75-skill-maintain.sh`,
`tests/skills/test_graduation_detect.py`. Toggle params: `skills.graduate_seen`,
`skills.graduate_kb`. **Surfaced on the dashboard:** `75-skill-maintain.sh` also writes
a committed, content-routed `graduation-candidates.json`; `build.py` `load_graduation()`
emits `window.GRADUATION` and `index.html` renders a Graduation-candidates panel
(fail-open empty state). Keeps the engine PII-clean. The data lives in the overlay.

**Situational example.** `security-review` reaches `seen: 30` and 8 KB. The daily
routine flags it in the marker file **and the dashboard's Graduation panel**. You run
the graduation: a lean `np-kb-security-review` skill is born (method in the body, depth
in `references/`), the strategy is marked `graduated`, and the detector stops flagging
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
The guaranteed path is `np-backcapture-sweep.sh` on `SessionStart` (backgrounded):
it re-runs capture + evaluator against the *previous* session's now-complete on-disk
transcript, deduped per `session_id`.

**Assets.** `episodic-capture.sh`, `np-backcapture-sweep.sh`,
`np-transcript-extract.py`. Toggle: `memory` (`memory.backcapture`).

**Situational example.** You finish a session and type `/exit`. No SessionEnd fires.
Nothing is lost: when you next start a session, the back-capture sweep finds that
completed transcript, summarizes it, and scores it, so the work still reaches episodic
+ metrics.

## Performance evaluator + signals

**Purpose.** Quantify how much nervepack actually helped a session, so the system can
be measured and improved instead of assumed-useful.

**Workflow.** At `SessionEnd` (and via the sweep), `np-eval-signals.py` extracts
deterministic signals (skills invoked, playbook fires/heeded, recall injections,
directive present, struggles, tokens) from fire-time markers the hooks dropped, then
a Haiku verdict adds score + helped/shortfalls/suggestions. Records land in a local
inbox.

**Assets.** `np-evaluator.sh`, `np-eval-signals.py`, `np-kb-evaluator-signals` (the
field reference). Toggle: `evaluator`.

**Situational example.** A session where you invoked three skills and heeded a playbook
scores higher on "nervepack helped" than one where the directive was present but no
skill fired. The low-help session generates a suggestion you can act on later.

## Metrics aggregation + dashboard

**Purpose.** Turn the per-session records into a committed time series and a visual
read on trends, wins, and struggles.

**Workflow.** The on-exit flush (`np-session-flush.sh`) promotes the inbox; the daily
`73-aggregate-metrics.sh` drains records into committed `dashboard/data/metrics.jsonl`;
`build.py` renders `metrics.js` for `dashboard/index.html`. A `74-open-dashboard.sh`
SessionStart hook opens it once per boot (guarded against the reconnect loop).

**Wiki navigation (left sidebar).** The same `build.py` pass also emits `window.WIKI`
into `metrics.js` (a grouped, searchable index of the overlay's `wiki/topics/<topic>/`
and `wiki/concepts/<concept>/` synthesis pages with their co-located sources, fields `{name, kind, last_updated, sources[], excerpt, html, topic}`).
`index.html` renders it as a grouped/collapsible left sidebar (entities / concepts /
sources-by-topic) with a client-side search filter; clicking an entry opens the
build-rendered HTML page in a new tab; Markdown stays the source (invariant 14).
`build.py` `md_to_html`/`render_pages` writes `data/{wiki,sources}/*.html` into the
content overlay at build time (content-resident & gitignored). Param-gated by
`evaluator.wiki_nav` (default on); off OR no `wiki/` dir → empty index, the sidebar
shows its empty state (fail-open). The wiki **data stays in the content overlay**
(`metrics.js`); the engine carries only the build + render code.

**Assets.** `73-aggregate-metrics.sh`, `dashboard/build.py` (`wiki_index()`),
`dashboard/index.html`, `74-open-dashboard.sh`, `open-dashboard.sh`, `np-core-dashboard`.
Toggle: `evaluator` (`dashboard_open`, `dashboard_serve`, `dashboard_port`, `wiki_nav`).

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

**Workflow.** Daily `75-skill-maintain.sh`: a deterministic detector
(`np-skill-budget.py`) flags any SKILL.md over the hard `split_kb` (8 KB); only then
does a gated Sonnet pass move overflow into `references/`, validated-or-reverted by
`np-skill-validate.py`. The same routine runs the graduation detector and the
ARCHITECTURE freshness check (both advisory).

**Assets.** `75-skill-maintain.sh`, `np-skill-budget.py`, `np-skill-validate.py`,
`np-graduation-detect.py`, `np-architecture-freshness.sh`,
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

**Assets.** `nervepack-session-directive.{sh,md}`,
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

**Assets.** `toggles.conf`, `np-toggle-lib.sh`, `nervepack-toggle.sh`, `np-core-toggle`.

**Situational example.** Playbook enforcement is too aggressive on a given machine. You
run `np-core-toggle` → disable `playbooks` locally; the guard hook no-ops there while
staying on everywhere else.

## Memory-store promotion

**Purpose.** Durable facts that landed in the session-scoped local memory store should
be promoted into a real skill, not stranded.

**Workflow.** A local cron (daily 08:00) runs `np-flow-memory-promote.md`: triage the
memory store, promote durable entries into the right skill, drop stale ones, commit +
push. Local-only because the cloud can't reach the memory dir.

**Assets.** `71-run-memory-promote.sh`, `agents/np-flow-memory-promote.md`. Toggle:
`memory`.

**Situational example.** You told a session to "remember" a new AWS profile name and it
went to local memory. The next morning's cron recognizes it as durable and folds it
into `np-env-secrets-refresh`, so every machine inherits it.

## Struggle escalation + skill-trigger recall

**Purpose.** Catch a session that's visibly struggling (or about to skip a skill) and
nudge it mid-flight, not just at the next session.

**Workflow.** `struggle-escalation.sh` (`UserPromptSubmit`, once/session) fires when
the playbook guard has tripped enough times after enough prompts, injecting a skill-
applicability reminder. `skill-trigger-recall.sh` matches skill-authoring prompt
patterns and reminds you to invoke `superpowers:writing-skills` first.

**Assets.** `struggle-escalation.sh`, `skill-trigger-recall.sh`, their installers.
Toggles: `evaluator.escalation`, `skills.trigger_recall`.

**Situational example.** Three tool calls into a task you keep tripping the playbook
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
(`NP_CONTENT_DIR`) holds wiki (with co-located sources) / memory (episodic+playbooks+strategies) / metrics + personal
skills. `np-content-lib.sh` (`np_content_dir`) resolves the overlay for every consumer;
unset falls back to the engine root (legacy single-repo).

**Assets.** `np-content-lib.sh`, `NP_CONTENT_DIR`, the `nervepack-content-example` repo.

**Situational example.** The graduation detector needs to scan *your* strategies. It
asks `np_content_dir`, gets your overlay path, and scans there. A public clone
with no overlay simply finds nothing and no-ops.

## CI PII guard + publish snapshot

**Purpose.** Make it structurally impossible for personal data to land in the (public-
to-be) engine.

**Workflow.** `np-publish-scan.py` scans for secrets/PII (incl. RFC1918 LAN IPs) with a
vetted false-positive allowlist; the `pii-guard` CI job runs it on every push/PR. The
pre-publish gate (`np-publish-snapshot.sh`) exports a history-free ref, scans it, and
refuses if dirty. It never pushes (public release stays human-gated).

**Assets.** `np-publish-scan.py`, `scan-allowlist.txt`, `np-publish-snapshot.sh`,
`PUBLISH.md`, the `pii-guard` CI job.

**Situational example.** You graduate a strategy into an engine skill but leave a real
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
