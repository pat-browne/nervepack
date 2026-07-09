# nervepack — architecture map (read before any code change)

> Cheap high-level map of how nervepack fits together. Read before any code change
> so you know what your change touches and can stay consistent with patterns that work.

## What nervepack is

A versioned hub of skills, rules, memory, and dev-env setup that follows Pat
across machines, **delivered into each AI session as user skills** (via
`.claude-plugin/`) and **wired into the session lifecycle by hooks + crons**. It
is mostly Bash/Python glue around the `claude` CLI plus Markdown knowledge. No
service, no daemon. Everything is a hook, a cron, or a committed file. (One
deliberate exception: the dashboard's localhost-only server,
`evaluator.dashboard_serve`, **default on** (opt-out). See the Dashboard row.)

## Skill namespaces (tiers)

| Prefix | Tier | Holds | Ships in |
|---|---|---|---|
| `np-core-` | cognition machinery | capture, recall, sync, toggle, contribute | **engine** |
| `np-flow-` | workflows | recurring agent prompts (`agents/*.md`) | **engine** |
| `np-kb-` | knowledge base | domain how-to (branding, chrome-ext, coding rules…) | **content overlay** |
| `np-env-` | environment | machine setup (ubuntu, plugins, vscode, secrets) | **content overlay** |

The prefixes name the namespace convention; they do **not** all ship from the same repo.
The **engine repo is machinery-only** — it ships `np-core-*` + `np-flow-merge-gate`. The
domain `np-kb-*`/`np-env-*` skills are **content** (personal/instance identity), delivered by
your content overlay (or a starter), not the public engine (PR #89). `30-link-skills.sh`
merges engine + overlay(s) at link time so every tier reaches the session.

## Feature catalog (every feature ↔ its toggle ↔ its code ↔ its design doc)

Toggles are declared in `engine/setup/toggles.conf`; every runtime check goes through
`np_enabled` in `engine/setup/np-toggle-lib.sh`. Flip with `np-core-toggle`. This table
is the code/toggle/doc **locator**; each feature's *purpose, enforcing workflow, and a
worked example* live in [`FEATURES.md`](FEATURES.md).

| Feature | Toggle | Core code | Design doc |
|---|---|---|---|
| **Session directive** ("consult nervepack first") | `directive` | `engine/setup/nervepack-session-directive.{sh,md}` | CLAUDE.md §"Why every session…" |
| **Episodic memory** (auto working-memory) | `memory` | `episodic-capture.sh`, `episodic-recall.sh`, `episodic-match.sh`, `episodic-scrub.sh`, `np-transcript-extract.py`, `agents/np-flow-episodic-maintain.md` | `specs/2026-06-02-episodic-memory-layer-design.md` |
| **Back-capture sweep** (reliable capture path) | `memory` (`.backcapture`; `backcapture_days` = max discovery window default 7, `backcapture_max` = per-sweep cap default 5) | `np-backcapture-sweep.sh` (SessionStart, backgrounded; persistent queue `~/.cache/nervepack/backcapture-queue/<sid>` tracks pending work independent of the current mtime window — enqueued once, processed oldest-first, survives aging past `backcapture_days`) | CLAUDE.md §"Back-capture sweep"; see invariant 12 |
| **Local memory promotion** | `memory` | `71-run-memory-promote.sh` | CLAUDE.md §"Memory-store promotion" |
| **Lessons** (auto-distilled, provenance-tagged, optionally enforced) | `lessons` (`.enforce`, default on) | `lesson-recall.sh`, `lesson-guard.sh`, `memory/lessons/`, `agents/np-flow-episodic-maintain.md` (distills capture `struggles[]`→`provenance: failure` and `strategies[]`→`provenance: success`) | `specs/2026-07-02-lessons-layer-merge-design.md` (was: `specs/2026-06-03-playbook-layer-design.md` + `specs/2026-06-05-nervepack-vs-sota-evaluation.md`) |
| **Performance evaluator** | `evaluator` | `np-evaluator.sh`, `np-eval-signals.py` | `specs/2026-06-03-performance-evaluator-design.md` |
| **Metrics aggregation** | `evaluator` (`.aggregate`; `retain_days=90` TTL prune, 0 = unlimited) | `73-aggregate-metrics.sh` | ↑ same |
| **Dashboard** | `evaluator` (`.dashboard_open`, default on) | `dashboard/build.py`, `dashboard/index.html`, `74-open-dashboard.sh` (SessionStart, once/boot), `open-dashboard.sh` (manual), `np-dashboard-launch.sh`, `np-core-dashboard`; resolved-suggestions ledger: `np-suggestion-resolve.sh` + `build.py` `load_resolved()` (routed via `np_content_dir`; `NP_RESOLVED_SUGGESTIONS` overrides); graduation panel: `build.py` `load_graduation()` ← committed `graduation-candidates.json` (written by `75-skill-maintain.sh`, content-routed; `NP_GRADUATION_CANDIDATES` overrides) → `window.GRADUATION`. Back-capture backlog panel: `build.py` `backlog_metrics()` ← local-cache `BACKCAPTURE_QUEUE_DIR`/`BACKCAPTURE_SEEN_DIR` (same dirs/env-var names as `np-backcapture-sweep.sh`, not committed content) + `memory.backcapture_days` toggle (via `np_toggle.param`, imported straight from `engine/setup/np_toggle.py`) → `window.BACKLOG = {pending, oldest_pending_days, ceiling_days, resolved_last_24h}`, rendered by `index.html` `renderBacklog()`. **Data bridge:** `index.html` loads `data/metrics.js` as a relative sibling; in a split layout `<engine>/dashboard/data` is a symlink into `<content>/dashboard/data`, created idempotently by `engine/setup/35-link-dashboard-data.sh` (run as bootstrap step 35, verified by `np-doctor.sh` `dashboard-data` capability). **Team-layer-aware (Phase 3):** `learned_counts()` merges `memory/lessons/` (split by provenance) across team+personal overlays per `team.merge`; metrics stay personal-only. | `specs/2026-06-03-p2-dashboard-design.md` |
| **Wiki navigation** (dashboard left-nav + search) | `evaluator` (`.wiki_nav`, default on) | `build.py` `wiki_index()` → `window.WIKI = {topics[], concepts[]}` in `metrics.js` (indexes overlay `wiki/topics/` + `wiki/concepts/`, resolved via `np_content_dir`; `WIKI_NAV` env gate); `index.html` grouped/collapsible sidebar (Topics — each topic nests its synthesis page + sources — and Concepts) + client-side search + build-rendered HTML pages opened in a new tab (`build.py` `md_to_html`/`render_pages` → `data/wiki/{topics,concepts}/*.html`; content-resident & gitignored). Data resides in the **content** overlay; engine carries code only. Phase 2b: `wiki_index()` scans the team+personal overlays (`np_merge_roots`/`np_merge_mode` via shell-out) and merges per `team.merge`. | `specs/2026-06-03-p2-dashboard-design.md` |
| **Suggestions review** | `evaluator` (`.dashboard_serve`, `.dashboard_port`, `.suggestions_top` params) | `np-suggestions-review.py` (list/clear), `np-dashboard-server.py` (opt-in localhost backend), `np-core-suggestions-review` | (this work) |
| **Suggestion implement/reject** (dashboard P3) | `evaluator` (`.implement`, `.implement_mode` `pr\|direct`) | `np-implement-suggestion.sh` (async agentic job; worktree-isolated; tries the engine repo first, then falls back to the content overlay via `np_content_dir` when the engine attempt is `NOT_IMPLEMENTABLE`/no-commit and a distinct git-tracked overlay is configured — a content-overlay success always lands with a direct push, independent of `implement_mode`), `agents/np-flow-implement-suggestion.md`, `np-dashboard-server.py` `/api/implement`, `index.html` buttons | `specs/2026-06-08-suggestion-implement-reject-design.md` |
| **Struggle escalation** (mid-session) | `evaluator` (`.escalation`; `escalation_min_struggles=2`, `escalation_min_prompts=3`) | `engine/setup/struggle-escalation.sh` (UserPromptSubmit, once/session), `57-install-escalation-hook.sh` | — |
| **Skill trigger recall** (prompt-pattern skill routing) | `skills` (`.trigger_recall`) | `engine/setup/skill-trigger-recall.sh` (UserPromptSubmit, once/session), `59-install-skill-trigger-hook.sh` | — |
| **Skill maintenance** (daily auto-split + advisory checks) | `skills` (`graduate_seen`/`graduate_kb` params) | `75-skill-maintain.sh`, `np-skill-budget.py`, `np-skill-validate.py`, `np-graduation-detect.py` (flags proven/over-budget lessons to graduate→skill; surfaces to log + `graduation-candidates` marker, never auto-promotes), `np-architecture-freshness.sh` (advisory map-drift), `agents/np-flow-skill-maintain.md` | `specs/2026-06-05-skill-maintenance-routine-design.md` |
| **Engine maintenance — refine** (weekly lint + cross-ref audit) | `maintain.refine` (sub of `maintain`, default on) | `76-run-refine.sh`, `agents/np-flow-scheduled-refine.md` | `specs/2026-06-19-provider-agnostic-scheduled-agents-phase1-design.md` |
| **Engine maintenance — compact** (weekly skill dedup + split proposals) | `maintain.compact` (sub of `maintain`, default on) | `77-run-compact.sh`, `agents/np-flow-weekly-compact.md` | `specs/2026-06-19-provider-agnostic-scheduled-agents-phase1-design.md` |
| **Cross-machine sync** | `sync` | `40-sync-nervepack.sh` | CLAUDE.md §"sync nervepack" |
| **Feature toggles** | (self) | `np-toggle-lib.sh`, `nervepack-toggle*.sh`, `toggles.conf` | `specs/2026-06-03-feature-toggles-design.md` |
| **Permission allowlist** | `allowlist` | `90/91-…-permissions.sh` | — |
| **Secrets refresh** | — | `np-env-secrets-refresh` skill | `specs/2026-05-26-secrets-refresh-design.md` |
| **Wiki/sources** (curated reference) | — | `wiki/topics/<topic>/` and `wiki/concepts/<concept>/` (each a folder = one synthesis page + co-located sources; concepts mirror topics — there is no separate top-level `sources/` dir), `log.md` | AGENTS.md §"Wiki layer" |
| **LLM-agnostic onboarding** | — | `np-llm.sh` (LLM-CLI seam), `engine/onboard/{ONBOARD.md,capabilities.json,adapters/}`, `np-doctor.sh`, `np-core-onboard` skill | `specs/2026-06-05-agnostic-onboarding-design.md` |
| **MCP layer** (model-agnostic surface) | `mcp` (`writes`/`contribute` params) | `engine/setup/np-mcp-server.py` (stdlib stdio JSON-RPC dispatcher), `engine/bin/nervepack-mcp` (launcher), `engine/setup/58-install-mcp.sh` (Claude Code registration), `engine/bin/nervepack-install` → `engine/setup/np-mcp-install.sh` (the **guided one-line install**: prompt content/team overlay → register → run the doctor; non-interactive falls back to defaults; test `tests/onboard/test_mcp_install.sh`), `engine/setup/tests/mcp/test_mcp_server.py`. **Team-layer-aware (Phase 3):** `_tool_recall` merges episodic/lesson recall across team+personal overlays per `team.merge`. | `specs/2026-06-08-nervepack-mcp-layer-design.md` |
| **Content seam** (engine/overlay split) | — (config: `NP_CONTENT_DIR`) | `engine/setup/np-content-lib.sh` (`np_content_dir` resolver + `np_content_dir_origin`/`np_content_is_explicit` — the single explicit-vs-implicit detector, issue #12; consumed across recall/guard hooks, skill link+index, metrics, MCP, doctor). Personal-content writers (71/72/73/75) **skip their commit** when the dir is the *implicit* engine-root fallback (NP_CONTENT_DIR unset AND no `~/.config/nervepack/content-dir`), so they never pollute the PII-clean engine; the doctor `content` check warns. A deliberate single-repo user opts in via the config file (origin `config`). Example overlay: the public `nervepack-content-example` repo. Optional **team** overlay (`NP_TEAM_DIR` / `~/.config/nervepack/team-dir`, toggle `team`) overrides personal skills + merged INDEX (Phase 1); resolved by `np_team_dir`/`np_team_dir_origin`. The team value may be a **comma-separated list of up to 4 dirs** (first = highest precedence), stacking `team[0] > … > team[n] > personal > engine`; `np_team_dirs` is the single parse/validate/cap point and `np_team_dir` is its highest-precedence first entry. Phase 2a: recall hooks (`lesson`/`episodic`) read across layers via `np-layer-lib.sh` (`np_content_layers`/`np_merge_mode`/`np_merge_roots`); mode = `team.merge` param (`override`\|`concatenate`\|`team-only`). Phase 2b: `wiki_index()` merges team+personal wiki overlays. Phase 3: `dashboard/build.py` `learned_counts()` and `engine/setup/np-mcp-server.py` `_tool_recall` merged — **team content layer complete through Phase 3** (metrics remain personal-only by design). | `specs/2026-06-09-nervepack-engine-content-architecture-design.md` |
| **CI PII guard** (secret/PII gate) | — (always-on CI job) | `publish/np-publish-scan.py` (secret/PII scanner; LAN-IP/RFC1918 rule, never loopback) + `scan-allowlist.txt`; CI job `pii-guard` in `.github/workflows/ci.yml`; pre-publish gate `publish/np-publish-snapshot.sh` (+ `publish/PUBLISH.md`); tests `engine/setup/tests/publish/` | `specs/2026-06-09-nervepack-engine-content-architecture-design.md` |
| **PII filter** (context-window and storage-time scrub) | `pii_filter` (default off) | `np-pii-filter.py`, `episodic-scrub.sh` (extended), `episodic-recall.sh` (extended), `lesson-recall.sh` (extended), `np_scrub.py` (extended, `NP_PII_FILTER=1`), `25-install-pii-deps.sh` | `specs/2026-07-06-pii-filter-design.md` |

## Runtime wiring — what fires what

**Lifecycle hooks** (registered in `~/.claude/settings.json` by `engine/setup/5x-install-*.sh`):

| Event | Scripts (in order) |
|---|---|
| `SessionStart` | `40-sync-nervepack.sh &` · `nervepack-session-directive.sh` · `74-open-dashboard.sh &` · `np-backcapture-sweep.sh &` |
| `UserPromptSubmit` | `episodic-recall.sh` · `lesson-recall.sh` · `struggle-escalation.sh` · `skill-trigger-recall.sh` |
| `PreToolUse` | `lesson-guard.sh` (matchers: `Bash`, `Read`) |
| `PreCompact` | `episodic-capture.sh checkpoint` |
| `SessionEnd` | `episodic-capture.sh session-end` · `40-sync-nervepack.sh exit &` · `np-evaluator.sh` · `np-session-flush.sh` (promotes both inboxes on exit; crons = backup) |

**Crons** (installed by `70-install-memory-cron.sh`):

| When | Job |
|---|---|
| Daily 08:00 | `71-run-memory-promote.sh` |
| Daily 08:30 | `72-run-episodic-maintain.sh` |
| Daily 09:00 | `73-aggregate-metrics.sh` |
| Daily 09:15 | `75-skill-maintain.sh` |
| Weekly Sun 09:30 | `76-run-refine.sh` (maintain.refine toggle, default on) |
| Weekly Wed 10:00 | `77-run-compact.sh` (maintain.compact toggle, default on) |

**Setup numbering:** `00–21` toolchain · `30` link-skills (+`60` index) · `35` link-dashboard-data (content bridge) · `40`
sync · `50–56` install hooks · `70` install crons / `71–77` cron bodies · `80–91`
vscode + permissions. Scripts are idempotent and run in order on a fresh box.

## The two data pipelines (the heart of the system)

Both follow the same shape: **a cheap hook captures → a local
`~/.cache/nervepack/` inbox → the on-exit flush (`np-session-flush.sh`) promotes
it into a committed layer immediately → a reader surfaces it.** The daily/weekly
crons are an **idempotent backup** (empty inbox = no-op).

**The reliable capture trigger is SessionStart, not SessionEnd** (invariant 12).
Claude Code kills slow SessionEnd `claude -p` hooks before they finish and `/exit`
doesn't fire SessionEnd at all, so the SessionEnd capture/evaluator are
**best-effort**; the `np-backcapture-sweep.sh` SessionStart hook is what actually
back-captures the previous session (from its now-complete on-disk transcript) by
re-running the same capture + evaluator. Same inboxes, same readers. Only the
trigger differs.

```
EPISODIC MEMORY
  SessionEnd ─ episodic-capture.sh ─ claude -p (haiku summary)
            └─▶ ~/.cache/nervepack/episodic-inbox/*.jsonl
                 └─ np-session-flush (on exit) → 72-maintain ─▶ memory/episodic/<topic>.md  (committed)
                      │   [backup cron: Sun 08:30]
                      └─ read by: episodic-recall.sh (UserPromptSubmit) + np-core-recall (/recall)

PERFORMANCE
  SessionEnd ─ np-evaluator.sh (np-eval-signals.py extracts signals+tokens) ─ claude -p (haiku verdict)
            └─▶ ~/.cache/nervepack/evaluator-inbox/*.jsonl
                 └─ np-session-flush (on exit) → 73-aggregate ─▶ dashboard/data/metrics.jsonl  (committed)
                      │   [backup cron: daily 09:00]
                      └─ build.py ─▶ metrics.js ─▶ dashboard/index.html (windowed to last N)
```

Record shapes (keep these stable; readers depend on them):
- **episodic inbox**: `{session_id, ts, project, cwd, mode} + {headline, body, candidate_topics[], keywords[], struggles[]}` (`session_id` lets the evaluator count this session's `struggles[]` cross-pipeline)
- **metrics**: `{session_id, ts, project, signals{skills_invoked[], playbook_fires, playbook_heeded, recall_injections, directive_present, directive_tokens, struggles, tool_calls, tokens{…}}, contribution_score, helped[], shortfalls[], suggestions[], assets_used[]}` (field-by-field source + zero-bias notes: `docs/FEATURES.md` "Performance evaluator + signals")

## Design invariants — the proven choices. Don't relitigate these silently.

1. **Hooks fail open.** Every lifecycle hook ends `exit 0` and routes each early
   return through a `bail()` that logs one dated line to a `*.log` in
   `~/.cache/nervepack/`. A hook must never break or block a session. (→ coding-rules §8)
2. **Headless `claude -p` rules** (→ `np-kb-claude-headless-scripting`):
   prompt via **stdin** not a trailing positional (variadic `--allowedTools` eats
   it); `--append-system-prompt` to stop it continuing the transcript; **cap input**
   and extract text first (`np-transcript-extract.py`); **and any hook that calls
   `claude -p` MUST set `NERVEPACK_AGENT=1` on the call and bail when that marker
   is set.** Headless `-p` re-fires the lifecycle hooks, so without the guard a
   SessionEnd hook recurses forever (§7). The runtime no longer calls `claude -p`
   directly: it goes through **`np-llm.sh`** (the backend-neutral LLM-CLI seam),
   which sets `NERVEPACK_AGENT` centrally and lets a non-Claude host swap the backend.
3. **Everything is toggle-gated.** New runtime behavior checks `np_enabled <feature>`
   and adds a row to `toggles.conf` (→ `specs/…feature-toggles`). Fail-open: unknown = on.
4. **Cheap model by default.** Summarizers/judges → `claude-haiku-4-5-20251001`;
   agentic crons → `claude-sonnet-4-6`. Never Opus in automation. (→ CLAUDE.md §"Model selection")
5. **Bash for glue, Python for parsing/logic** (→ CLAUDE.md §"Harness language policy").
6. **Every script has a regression test** in `engine/setup/tests/` (stdlib `unittest` /
   plain bash; stub `claude` via `CLAUDE_BIN`). The whole suite runs via
   `engine/setup/tests/run-all.sh` (hermetic, zero third-party deps outside `e2e/`);
   CI runs it as the blocking `regression` job and gates `main` on it. (→ coding-rules §5)
7. **Skills stay lean** (~6 KB soft / 8 KB hard; overflow → `references/`), enforced
   daily by skill-maintain.
8. **GUI side-effects guard once-per-boot** (the `74` dashboard open). SessionStart
   fires repeatedly and a raw GUI open self-sustains a reconnect loop (§4).
9. **Commits:** conventional prefix (`skill()/setup()/feat()/fix()/docs()/manual()/evaluator()/agent()`),
   authored as the repo's configured git identity, **no LLM-attribution trailer** (→ coding-rules §6). Ask before pushing.
10. **Concurrency-safe sync:** fast-forward only, re-check the tip before any
    destructive git op; never force-push a concurrent agent's branch.
11. **Cache-stable context injection** (Manus): the SessionStart directive is a
    **byte-stable prefix** (no timestamps/volatile fields, regression-tested). All
    variable, session-specific context (episodic/lesson recall) is injected
    **later** via `UserPromptSubmit`, never interleaved into the stable block, so the
    KV-cache survives. nervepack's own injection cost is attributed via
    `directive_tokens` in the evaluator signals.
12. **SessionEnd is unreliable for slow work; SessionStart is the reliable trigger.**
    Claude Code exits without awaiting slow SessionEnd hooks and `/exit` doesn't fire
    SessionEnd at all (GH #35892/#41577), so any SessionEnd step that calls `claude -p`
    (capture, evaluator) is **best-effort**. The guaranteed path is the SessionStart
    `np-backcapture-sweep.sh`, which back-captures the previous session from its
    complete on-disk transcript. New per-session capture/scoring work must ride the
    sweep (or another awaited trigger), never depend on SessionEnd completing.
13. **Pre-flight gates check the backend, not the `claude` binary.** A hook/cron that
    needs a model must gate on `${NP_LLM_BACKEND:-claude}`, never on `[[ -x "$CLAUDE" ]]`
    alone: require the `claude` binary only on the `claude` backend; the `local` backend
    has its own prerequisites (`complete` → `NP_LLM_BASE_URL`/`MODEL_CHEAP` via
    `np-llm-local.py`; `agent` → `NP_LLM_AGENT_CMD`). A bare claude-binary check silently
    disables the whole pipeline on a non-Claude host even though the backend works. This
    is the #4b finding behind the five backend-aware gates (capture, evaluator, `71`/`72`/`75`).
    (→ invariant 2; the seam already owns backend dispatch, don't re-scatter `claude -p`)
14. **Markdown is the internal representation; HTML is only for human render.**
    Everything the model ingests (skills, wiki, sources, injected context) stays
    **Markdown**. Measured on this corpus (2026-06-17), the *same* content as HTML costs
    **~26% more tokens** on a clean render (real-world HTML 2–10×; published HTML→MD
    conversions report ~67–87% token savings), while Markdown is only **~5% over bare
    plain text** (structure for nearly free, and the format LLMs are trained most on).
    HTML earns its place **only** for human-facing rendered pages (e.g. the dashboard's
    "open the source" tab, where the model never reads it) or merged-cell tables
    (`colspan`/`rowspan`, which nervepack content doesn't use). So: **author/store
    Markdown, render → HTML at build time for humans, never feed HTML to the model.**
    (Resolves the highest-priority "HTML vs Markdown efficiency" roadmap item.)
15. **`main` branch protection keeps `enforce_admins: false`.** The auto-commit
    crons (`np-flow-episodic-maintain`, `weekly-compact`, `scheduled-refine`, the
    metrics aggregator, and `np-implement-suggestion.sh` direct mode) push
    **directly to `main`** as the repo owner. Classic branch protection requires a
    PR + the three blocking CI checks + linear history for *contributors*, but
    admins — and therefore those crons — bypass it via `enforce_admins: false`.
    Enabling admin enforcement, or requiring ≥1 approval, silently breaks every
    auto-push cron. The required status-check contexts are the CI job `name:`s
    verbatim (`Syntax sweep (stdlib-only)` / `Regression suite (zero-dep)` /
    `Secret/PII guard (terminal gate)` / `Windows suite (Git-bash)` — green end-to-end
    under Git-bash on `windows-latest` — and `Bash-free MCP suite (no Git-bash)`, the
    git-for-windows-free MCP gate: `windows-latest` with the Git-bash dirs stripped
    from `PATH`, running the ported MCP surface); `dashboard-e2e` stays informational
    and must never be a required check. (→ invariant 10; CLAUDE.md/AGENTS.md §concurrency)
16. **OS/host backends are portable-shell-shelling-to-the-native-tool, never a
    native-shell script.** The three scheduler backends are all bash that shell to the
    OS scheduler: cron (Linux), `launchctl` (macOS, `70-install-memory-launchd.sh`),
    `schtasks.exe` (native Windows, `70-install-memory-schtasks.sh`, run under
    Git-bash). A Windows-native `.ps1` was rejected: invariant 6 requires every script
    to have a regression test in the **zero-dep Ubuntu CI suite**, and PowerShell isn't
    on those runners — a `.ps1` ships untested. A bash installer is stub-testable on
    Linux (`NP_*_FORCE` + a stub `schtasks`/`launchctl`/`uname` on PATH) exactly like
    its siblings, and Layer-1 Windows already requires Git-bash for the `7x` job bodies,
    so bash availability is a given. Same reasoning for the **hook shim**: rather than a
    `.cmd`/PowerShell entrypoint, `np-hook-lib.sh` wraps the stored command
    `bash -lc '<cmd>'` on a MINGW/MSYS kernel (`NP_HOOK_WRAP`) so PowerShell-dispatched
    hooks resolve to Git-bash, leaving Linux/macOS byte-for-byte unchanged. (→ invariant
    6; the bash-vs-Python language policy in AGENTS.md — native-shell scripts are the
    one form that can't be CI-tested, so they're out for cross-platform glue.)

## Change-impact map — touch X, then check Y

| If you change… | Also check / update |
|---|---|
| **content layer dir names** (`memory/{episodic,lessons}`, `wiki/{topics,concepts}/<x>/`) | `np_layer_dir`/`np_layer_roots` (the single resolver — change the subpath here, not at each consumer); the two recall hooks (`episodic-recall.sh`, `lesson-recall.sh`), `lesson-guard.sh`, `73`/`75`, `dashboard/build.py` (`wiki_index`, `learned_counts`), `np-mcp-server.py` `_tool_recall`; the maintain-agent write path (`agents/np-flow-episodic-maintain.md`); the example-layout fixture + `tests/content/test_example_layout.sh` (the anti-drift contract) |
| any **lifecycle hook script** | its registration in `settings.json` (`5x-install-*.sh` → `np-hook-lib.sh np_register_hook`), fail-open + `bail()`, the `NERVEPACK_AGENT` guard (all globally-registered hooks must carry it — not only those that call `claude -p`), and `engine/setup/tests/`. On native Windows `np-hook-lib.sh` wraps the stored command as `bash -lc '<cmd>'` (`NP_HOOK_WRAP`, auto on a MINGW/MSYS kernel) so PowerShell-dispatched hooks resolve to Git-bash — keep hook commands single-quote-free |
| **`episodic-capture.sh`** (or its prompt/schema) | `episodic-recall`, `episodic-match`, `episodic-scrub`, dedup fingerprint, `np-flow-episodic-maintain` (consumes the inbox shape, incl. `struggles[]`→lessons `provenance: failure` and `strategies[]`→lessons `provenance: success`), `np-transcript-extract.py` |
| **the lessons layer** (recall, enforcement, or distillation) | the capture schema (`struggles[]`/`strategies[]`), `np-flow-episodic-maintain` §5b/5c (writes `memory/lessons/`, tags `provenance`, adds `enforce` only when warranted), `lesson-recall.sh`/`lesson-guard.sh` + their install (`53-install-lesson-hooks.sh`), the `lessons`/`lessons.enforce` toggle, the dashboard "learned" counts (`build.py`, split by `provenance`), and the **graduation detector** (`np-graduation-detect.py` reads a lesson's `seen`/`status` + byte size — keep those stable; `skills.graduate_seen`/`graduate_kb` params; `75-skill-maintain.sh` wiring + `tests/skills/test_graduation_detect.py`) |
| **`np-evaluator.sh`** / the **metrics record shape** | `np-eval-signals.py`, `73-aggregate-metrics.sh`, `dashboard/build.py`, the panels in `dashboard/index.html`, `sample-metrics.jsonl`, the dashboard test |
| **add a model call anywhere** | call `np-llm.sh` (don't hardcode `claude -p`); it sets `NERVEPACK_AGENT=1` — still guard the calling hook (invariant 2) |
| **shell out to bash from Python** (any `.py` that runs a `.sh` or `bash -c`) | route the argv through `engine/setup/np_bashlib.py` `argv()` (runtime) or `engine/setup/tests/_lib/nptest.py` `sh`/`u`/`bash_eval` (tests). On Windows a bare `bash` resolves to `C:\Windows\System32\bash.exe` (WSL, no distro) not Git-bash, and backslash/`.sh` paths can't be opened — both helpers fix this and are no-ops off Windows. `NP_BASH` (exported by `run-all.sh` and `engine/bin/nervepack-mcp`) pins the interpreter; the suite runs green on `windows-latest` (required CI gate). Current callers: `np-mcp-server.py`, `np-dashboard-server.py`, `np-eval-signals.py`, `dashboard/build.py`. (→ invariant 16; [[np-kb-testing-ci]] §8) |
| **`np-toggle-lib.sh`** / **`np-content-lib.sh`·`np-layer-lib.sh`** / **`episodic-match.sh`** / **`np-doctor.sh`** / **`40-sync-nervepack.sh`** (resolvers + recall + doctor + sync) | their **in-process Python ports** `engine/setup/np_toggle.py` (`enabled`/`param` + the write/status surface `scope`/`features`/`set_local`/`is_local_set`/`status_lines`), `np_content.py` (`content_dir`/`origin`/`is_explicit`/`team_dir`/`content_layers`/`merge_mode`/`merge_roots`), `np_episodic_match.py` (`match`), and `np_doctor.py` (`report` — the deterministic CORE checks only), `np_sync.py` (`sync` — the defensive engine fast-forward), `np_model.py` (`complete` — the single-shot model seam for the ported capture/evaluate; mirrors `np-llm.sh complete`, `agent` mode stays bash), `np_scrub.py` (`scrub` — the byte-exact secret-redaction port of `episodic-scrub.sh`, used by the ported capture before the inbox write), `np_capture.py` (`capture` — the episodic-capture pipeline: gate → transcript-extract → `np_model` → json-extract → `np_scrub` → inbox note, building the record to match `jq -nc`), and `np_evaluator.py` (`evaluate` — the evaluator pipeline: signals → transcript-extract → `np_model` → json-extract → cost-aware suggestion → `np_scrub` → inbox record) must stay equivalent — the long-running MCP server resolves toggles+content, matches recall, reads the toggle status table, writes **local** toggle changes, and runs the engine sync **in-process** via these (no bash subprocess per request; shared-feature toggle writes — `toggles.conf` + git commit/push — managed-permission scripts, and the sync's team-layer ff + skill relink still need bash; `NP_MCP_PURE_PYTHON=0` falls back to shelling to the bash originals). The **doctor, sync, capture, and evaluate are hybrids**: `_tool_doctor`/`_tool_sync`/`_tool_capture`/`_tool_evaluate` run the full bash script whenever bash is available (no fidelity loss — doctor covers `llm-cli`+adapter, sync covers the team ff + relink), and only fall back to the Python port (doctor: core checks, `llm-cli`/adapter reported **N/A** off the MUST gate; sync: engine ff only) on a host with **no bash**. A/B parity is enforced by `engine/setup/tests/mcp/parity/test_{toggle,toggle_write,content,episodic_match,doctor,sync,model,scrub,capture,evaluator}_parity.sh` (byte-identical stdout/files across footgun tables; matcher: header/separator skip, scoring, `sort -rn` tie-break, hyphenated keywords; doctor: the five core-check lines in a controlled git/content/toggle env; toggle_write: the status table + `set_local` across new keys/overwrites/dotted params; sync: the outcome message across up-to-date/dirty/ahead/ff/diverged/not-a-git + gate/throttle/dry-run, modulo timestamp). Change one side → the parity test goes red until the other matches. The git-for-windows-free MCP milestone is **complete** (overlay `specs/2026-06-30-git-for-windows-free-mcp-design.md`): every MCP tool runs bash-free except `flush`/`maintain` (agent-mode crons, deferred — they refuse cleanly on a bash-free host), and `engine/bin/nervepack-mcp.cmd` spawns the server without bash. The `NP_MCP_PURE_PYTHON=0` escape hatch back to the bash originals is **kept** (reversibility). Bash stays the source of truth for the hot-path hooks/crons. Bash-free proof: `engine/setup/tests/mcp/test_bashfree.py` + the `windows-bashfree` CI lane (keeps native git, strips only the Git-bash dirs). |
| **`np-llm.sh`** (the LLM-CLI seam) | every runtime caller (capture, evaluator, 71/72/75); BOTH backend branches (`claude`, and `local` → `engine/setup/np-llm-local.py` for any OpenAI-compatible endpoint via `NP_LLM_BASE_URL`/`_API_KEY`/`_MODEL_CHEAP`); the `complete`/`agent` contract (`agent` on `local` needs `NP_LLM_AGENT_CMD`); `engine/setup/tests/llm/` |
| **`engine/onboard/capabilities.json`** (the contract) | `np-doctor.sh` (reads it), `ONBOARD.md`, the `np-core-onboard` skill, and host `adapter.json` manifests |
| **`np-session-flush.sh`** (on-exit promotion) | its `NERVEPACK_AGENT` guard (the maintain step calls `claude -p`; without it SessionEnd recurses), that it stays LAST in SessionEnd (after capture+evaluator write the inboxes), that the crons remain idempotent backups, and that the **detach has a non-`setsid` fallback** (macOS has no `setsid` → `nohup`+`disown`, else the slow maintain step runs synchronously and Claude Code cancels the SessionEnd hook) |
| **`np-backcapture-sweep.sh`** (the reliable capture trigger) | it reuses `episodic-capture.sh` + `np-evaluator.sh` (keep their stdin payload contract `{session_id,transcript_path,cwd}` stable — Phase B reconstructs it from the queue file, not from a fresh `find`); its `56-install-*` registration (SessionStart, `&`); the `memory.backcapture` toggle + `backcapture_days` (max discovery window)/`backcapture_max` (per-sweep processing cap) params; the two-phase design — Phase A discovery/enqueue into `BACKCAPTURE_QUEUE_DIR` (one-way ratchet, survives the item's mtime aging past `backcapture_days`) vs Phase B processing oldest-enqueued-first out of the queue; dedup vs `metrics.jsonl` sids + the per-sid claim marker (`BACKCAPTURE_SEEN_DIR`); invariant 12; its test (`tests/episodic/test_backcapture.sh`, incl. the oldest-first-ordering and tracked-past-window cases) |
| **`np-mcp-server.py`** (the dispatcher) | the stdin/arg contracts of every wrapped script (`np-doctor.sh`, `episodic-match.sh`, `nervepack-toggle.sh`, `dashboard/build.py`, and the Phase-6 scripts); the `mcp`/`mcp.writes`/`mcp.contribute` toggles; the protocol method allowlist; `engine/setup/tests/mcp/` |
| **a wrapped script's CLI/stdin contract** | `np-mcp-server.py` is now a second caller alongside the hooks — update its call site |
| **`np-mcp-install.sh`** (the guided installer) | it writes `~/.config/nervepack/{content-dir,team-dir}` (must match `np-content-lib.sh`'s resolver paths — `$HOME/.config`, not XDG), calls `58-install-mcp.sh` for registration and `np-doctor.sh` for verification, and **must never flip the shared `team` toggle** (that commits to the engine repo — the overlay is on by default); keep the non-interactive default-on-empty-stdin behavior; `engine/bin/nervepack-install` is the one-line wrapper; `engine/setup/tests/onboard/test_mcp_install.sh`; `engine/onboard/MCP.md` documents it |
| **`np-content-lib.sh`** / content-dir resolution | every content-dir consumer (recall/guard hooks, `30-link-skills`, `60-generate-index`, `73-aggregate`, `np-backcapture-sweep`, `np-mcp-server.py`, `np-suggestion-resolve.sh` (resolved-suggestions ledger default), `build.py` (`_content_dir()` mirrors the resolver — used for `memory/lessons/` AND the resolved-suggestions default via `default_resolved()`; `NP_LESSONS_DIR`/`NP_RESOLVED_SUGGESTIONS` still override), `np-doctor` `content` check); the backward-compat default (unset → `$NP`); **`np_content_dir`'s stdout MUST stay byte-identical** — the explicit-vs-implicit signal lives in the sibling `np_content_dir_origin`/`np_content_is_explicit` (issue #12), which the personal-content writers (71/72/73/75) gate their commit on (skip on implicit fallback, fail-open) and the doctor warns on; `engine/setup/tests/content/` (incl. `test_writer_implicit_fallback.sh`). `np_team_dir`/`np_team_dir_origin` consumers: `30-link-skills`, `60-generate-index`, `np-doctor`, `40-sync`. `np_team_dirs` (the comma-list resolver; ≤4 cap, first=highest) is the new single parse point — `np_team_dir` returns its first line; consumers 30-link-skills / 60-generate-index / 40-sync / doctor now iterate `np_team_dirs`. |
| **`np-layer-lib.sh`** / **`team.merge`** param | the two recall hooks (`lesson-recall.sh`, `episodic-recall.sh`) that call `np_content_layers`/`np_merge_mode`/`np_merge_roots`; `np-doctor.sh` (reports the resolved mode); `dashboard/build.py` `wiki_index()` (live consumer — shells out to `np_merge_roots`/`np_merge_mode`; fail-open to personal-only); `dashboard/build.py` `learned_counts()` (Phase 3 — unions `memory/lessons/` across team+personal overlays per `team.merge`, split by provenance; metrics stay personal-only); `engine/setup/np-mcp-server.py` `_tool_recall` (Phase 3 — merges episodic/lesson recall across layers per `team.merge`); `engine/setup/nervepack-session-directive.sh` (feeds each merge root's `directive-routing.md` fragment, team>personal, so a team overlay's domain-skill routing reaches sessions — fail-open, byte-stable; test `tests/setup/test_directive_team_routing.sh`). `np_content_layers`/`np_merge_roots` now span all configured team roots, not just the first (team-only mode keeps every team root). |
| **`publish/np-publish-scan.py`** (the PII guard) | `scan-allowlist.txt` (vetted fake-token FPs only — never real PII) and the scanner's own `SKIP_FILES` (its source + its tests, incl. `test_snapshot.sh`, + the allowlist hold detection patterns by design — a new test that plants a fake secret MUST be added to `SKIP_FILES`); `publish/np-publish-snapshot.sh` is now a second consumer (it runs the scanner over a history-free export); the `pii-guard` CI job in `.github/workflows/ci.yml`; `engine/setup/tests/publish/{test_scan.py,test_no_engine_pii.py,test_snapshot.sh}` (the second asserts the engine tree scans clean) |
| **`publish/np-publish-snapshot.sh`** (the pre-publish gate) | the scanner it calls (`np-publish-scan.py`), `publish/PUBLISH.md` (the runbook documenting it), and `engine/setup/tests/publish/test_snapshot.sh`. It NEVER pushes — the public `gh repo create --public` stays a manual, human-gated step (ARCHITECTURE has no auto-publish path) |
| **maintenance-agent commit identity** (`agents/np-flow-*.md`) | uses the runner's git config, else `NP_GIT_AUTHOR_*`, else a neutral bot (never hardcode a person); `engine/setup/tests/publish/test_no_engine_pii.py`; the onboard env doc. `pat-browne`/the canonical repo URL are KEPT project identity (not PII). |
| **`engine/setup/tests/run-all.sh`** / the test harness | `_lib/harness.sh` + `_lib/report.sh` (hermetic-env + report helpers); the `meta/test_run_all.sh` meta-test (tests the runner itself); the `regression` CI job in `.github/workflows/ci.yml` (blocking, gates `main`); and `engine/setup/tests/README.md`. Note: `e2e/` stays excluded from the default run; use `--with-e2e` explicitly. |
| **`engine/setup/tests/e2e/`** (Playwright dashboard suite) | `requirements.txt` (pinned deps — update when Playwright version changes); `harness.py`'s server env contract (`NP_IMPLEMENT`, `NP_METRICS`, `NP_RESOLVED_SUGGESTIONS`, `NP_IMPLEMENT_STATUS_DIR`, `NP_DASH_PORT`); and the `dashboard-e2e` CI job (informational, `continue-on-error: true` — never a merge gate). This is the ONLY suite with a third-party dependency; keep it isolated in `e2e/` so the rest of the suite stays zero-dep. |
| **`main` branch protection** (rules / required checks) | keep `enforce_admins: false` so the auto-commit crons (`7x`, `np-implement-suggestion` direct mode) keep pushing directly; the required status-check contexts must match the CI job `name:`s exactly (`Syntax sweep (stdlib-only)` / `Regression suite (zero-dep)` / `Secret/PII guard (terminal gate)` / `Windows suite (Git-bash)` / `Bash-free MCP suite (no Git-bash)`); `dashboard-e2e` stays informational and MUST NOT be required; invariant 15 |
| **`toggles.conf`** (add/rename a feature or param) | every `np_enabled`/`np_param` caller, `nervepack-toggle*` menus, and the feature catalog above; note: adding a param with a default that prunes historic data (e.g. `evaluator.retain_days`) can cause existing test records to be pruned — tests with old timestamps must set `NP_TOGGLES_CONF` to control `retain_days` |
| **`nervepack-session-directive.md`** | this injects into **every** session globally — high blast radius; keep it lean |
| **a cron body (`7x`)** | its schedule entry in ALL THREE scheduler backends — `70-install-memory-cron.sh` (Linux crontab), `70-install-memory-launchd.sh` (macOS LaunchAgents), `70-install-memory-schtasks.sh` (native-Windows Task Scheduler, runs under Git-bash); remember its `claude -p` fires SessionEnd hooks (set the guard); 76/77 also need their `maintain.refine`/`maintain.compact` toggle rows in `toggles.conf` |
| **`dashboard/` data shape or build** | `build.py`, `index.html`, the build test, and the committed `metrics.js` (rebuild from real `metrics.jsonl`). The build emits `window.METRICS`/`LEARNED`/`TOKENS_SAVED`/`WIKI`/`GRADUATION`/`BACKLOG` into one `metrics.js`; `BACKLOG` (`backlog_metrics()`) is the one field NOT derived from `metrics.jsonl` or committed content — it reads `np-backcapture-sweep.sh`'s local-cache queue/seen dirs live at build time, so it's only meaningful on the machine that actually runs the sweep (a fresh checkout/CI renders its fail-open zeros, same as a missing `graduation-candidates.json`); `window.WIKI = {topics[], concepts[]}` — the **wiki index** (`wiki_index()`, `evaluator.wiki_nav` / `WIKI_NAV` env, sourced from overlay `wiki/topics/` + `wiki/concepts/`) is **content data** — keep it out of the engine repo, and pass `WIKI_NAV` from `73-aggregate-metrics.sh` + `open-dashboard.sh`; new render step (`md_to_html`/`render_pages`) writes `data/wiki/{topics,concepts}/*.html` — keep escaping + href-sanitization (see render tests) |
| **`engine/setup/35-link-dashboard-data.sh`** (dashboard data bridge) | the `dashboard-data` capability in `engine/onboard/capabilities.json`; the `np-doctor.sh` `dashboard-data` core check; `engine/setup/tests/setup/test_link_dashboard_data.sh`; and the **Dashboard** row of this feature catalog. The symlink `<engine>/dashboard/data -> <content>/dashboard/data` is the bridge `index.html` relies on; don't remove it. |
| **the suggestions-review engine** (`np-suggestions-review.py`) | it imports `dashboard/build.py` (`_norm`/`load_resolved`/`load_records`) — keep those stable; the server (`np-dashboard-server.py`) and the `np-core-suggestions-review` skill both shell out to it; its test |
| **`np-dashboard-server.py`** (the opt-in daemon) | keep it **127.0.0.1-only** + path-sanitized + fixed route allowlist; `np-dashboard-launch.sh` starts it; the `evaluator.dashboard_serve/_port/suggestions_top` params; `index.html`'s http-only buttons; its test |
| **suggestion implement** (`np-implement-suggestion.sh` / `/api/implement`) | the detached-spawn route stays under the CSRF guard; keep the job's lock + **worktree isolation** (the agent runs in a throwaway `git worktree` off the committed base — a dirty main tree no longer blocks implement and the agent's commit can't sweep the user's WIP; direct mode advances local base only when clean) + `NOT_IMPLEMENTABLE`/no-commit handling; the job MUST commit its resolution artifacts (`resolved-suggestions.txt`+`metrics.js`) so it leaves the tree clean (else the next implement refuses "dirty"); it writes a per-suggestion status file (`implement-status/<hash>.json`) that the dashboard polls via `/api/implement-status`; untrusted text is nonce-delimited (prompt-injection); `agents/np-flow-implement-suggestion.md` (must NOT push/PR — the wrapper owns the remote); `evaluator.implement`/`implement_mode` params; the Implement/Reject + Mode buttons + status polling in `index.html`; both tests (`test_implement.sh`, server test) |
| **the `evaluator` toggle params** (`dashboard_serve`/`dashboard_port`/`suggestions_top`) | `np-dashboard-launch.sh`, `np-dashboard-server.py`, and the feature catalog above |
| **np-instruction-block.sh** (managed instruction-file block) | its test (`tests/onboard/`); the `knowledge` capability hint in `capabilities.json`; `ONBOARD.md` recipe; never run by default on a host that already injects the directive via a session-start hook (double-injection) |
| **add/remove a skill** | `30-link-skills.sh` (relinks + regenerates `INDEX.md`), `.claude-plugin/plugin.json` |
| **the setup ordering** | idempotency + the `00→91` numbering contract (fresh-box bootstrap runs them in order) |

## Before you commit — the cheap checklist

- [ ] Read this map; confirmed the **change-impact** rows for what you touched.
- [ ] New runtime behavior is **toggle-gated** and **fails open**.
- [ ] Any new `claude -p` call sets `NERVEPACK_AGENT=1` and the hook is guarded.
- [ ] A **regression test** in `engine/setup/tests/` covers the change (red→green).
- [ ] Conventional commit prefix, authored as the repo's configured git identity, **no AI trailer**.
- [ ] If you made a new durable decision, fold it into the right skill/spec (→ `np-core-contribute`).

## Where to read more (the "child docs" — depth lives here, not duplicated above)

- **Protocols & conventions:** `AGENTS.md` (tool-neutral manual) + `CLAUDE.md` (Claude Code wiring; `@import`s AGENTS.md).
- **Per-feature design:** the design specs + plans live in the **content overlay**, not the engine (`$NP_CONTENT_DIR/docs/superpowers/{specs,plans}/`; filenames like `*-design.md` are referenced by name in the feature catalog above for provenance). Brainstorm/plan output is content, so a public engine-only clone won't carry them. Historical/one-time: `2026-06-03-nervepack-rebrand-design.md` (the brain→nervepack rename, not a live subsystem). In progress (Phases 1–5 built: `np-llm.sh`, the onboard contract, the doctor, the Claude adapter, the `np-core-onboard` skill; Goose validation pending): `2026-06-05-agnostic-onboarding-design.md` (LLM-agnostic onboarding).
- **Behavioral rules / gotchas:** `skills/np-kb-coding-rules`, `skills/np-kb-claude-headless-scripting`, `skills/np-kb-branding`.
- **Human overview & bringup:** `README.md`. **Deferred work:** `ROADMAP.md`. **Audit trail:** `log.md`.
- **Skill catalog:** `INDEX.md` (auto-generated; scan before adding a skill).
