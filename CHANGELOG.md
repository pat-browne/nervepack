# Changelog

All notable changes to the nervepack **engine** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims for
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This tracks the reusable engine, so the machinery, skills, onboarding, and MCP surface.
It does not track any individual user's personal content overlay.

## [Unreleased]

### Fixed
- **Dashboard shows no metrics on a fresh clone (split layout).** Root cause: the
  `<engine>/dashboard/data` → `<content>/dashboard/data` symlink bridge had no
  bootstrap step — it was created once by hand during the engine/content split
  migration and gitignored, so every new clone was missing it and the dashboard
  loaded no metrics. Fix: `engine/setup/35-link-dashboard-data.sh` (idempotent
  bootstrap step, numbered between 30-link-skills and 40-sync) creates or repairs
  the symlink on a fresh clone. A missing bridge is now surfaced by `np-doctor.sh`
  as a WARN on the new `dashboard-data` SHOULD capability. Regression test:
  `engine/setup/tests/setup/test_link_dashboard_data.sh`.

### Added
- **Critical-path guard** (`engine/setup/np-path-check.py`). Scans docs and skills for
  references to nervepack's `setup/`/`onboard/` scripts and fails on a stale pre-split
  path (`setup/x` where the file now lives at `engine/setup/x`) or an `engine/…` path to
  a file that doesn't exist. Runs in CI via the auto-discovered
  `tests/docs/test_critical_paths.sh` (no workflow change — it rides the `regression`
  gate) and is a step in the install walkthrough (`docs/GETTING-STARTED.md`). Fixes the
  fleet of stale flat-layout path references the engine/content split left behind in the
  `np-core-*` skills, the onboard contract, and `MCP.md`.
- **Team content overlay.** An optional third overlay above your personal content,
  so a team can share a curated baseline of skills, playbooks, strategies, and wiki
  without giving up private per-person memory. Point at it with `NP_TEAM_DIR` (or
  `~/.config/nervepack/team-dir`) and the stack becomes `team > personal > engine`.
  Reads merge with the team winning, and writes stay personal unless you explicitly
  target the team (`np-core-contribute --layer team`). Skills are override-only, and
  the topic layers combine per the `team.merge` param (`override` default,
  `concatenate`, or `team-only`). Metrics stay personal-only by design. Gated by the `team` toggle
  (dormant until a team dir resolves). Complete through Phase 3, so the recall hooks
  (`np-layer-lib.sh`), the dashboard wiki index and learned-counts, and the MCP
  `_tool_recall` all merge across layers.
- **Guided one-line MCP installer** (`engine/bin/nervepack-install` →
  `np-mcp-install.sh`). It prompts for the content/team overlay, registers the server,
  and runs the doctor. Non-interactive falls back to defaults.
- `76-run-refine.sh` and `77-run-compact.sh`: local cron bodies for the refine
  (frontmatter lint + cross-ref audit) and compact (skill dedup + split proposals)
  agents. Default-on, gated by `maintain.refine` / `maintain.compact` toggles.
  Installed idempotently by `70-install-memory-cron.sh` (Linux) and
  `70-install-memory-launchd.sh` (macOS). Run via `np-llm.sh` agent mode —
  provider-agnostic (claude backend or `NP_LLM_AGENT_CMD`), fail-open.
- `maintain` / `maintain.refine` / `maintain.compact` toggle entries in
  `toggles.conf` (default on).

### Changed
- **Canonical content layout.** The three agent-owned layers moved under one
  `memory/` root (`memory/{episodic,playbooks,strategies}/`), and sources now live
  co-located inside their topic folder (`wiki/topics/<topic>/`) instead of a
  top-level `sources/` dir. Concepts are folders under `wiki/concepts/<concept>/`,
  and the old `wiki/entities/` merged into topic folders. A single resolver
  (`np_layer_dir`/`np_layer_roots`) owns the `memory/<layer>` subpath so every
  reader (recall hooks, playbook guard, aggregate, dashboard, MCP) agrees. The
  `nervepack-content-example` overlay ships in this layout, and
  `tests/content/test_example_layout.sh` guards against drift.
- **MCP surface runs bash-free.** In-process Python ports of the toggle, content,
  layer-recall, doctor, sync, model, scrub, capture, and evaluate paths let every
  MCP tool run without Git-bash on Windows (agent-mode `flush`/`maintain` refuse
  cleanly on a bash-free host). Each port is parity-locked to its bash original by a
  byte-identical A/B test, and `NP_MCP_PURE_PYTHON=0` still falls back to the bash
  scripts. The bash-free Windows CI lane is now a required merge gate. Bash stays the
  source of truth for the hot-path hooks and crons.
- `agents/np-flow-scheduled-refine.md` and `agents/np-flow-weekly-compact.md`
  genericized: removed hardcoded repo name, "Anthropic cloud (CCR)" assumption,
  and residual personal framing. Prompts now read correctly whether run by a local
  cron, a cloud routine, or an OSS runner.
- `70-install-memory-cron.sh` and `70-install-memory-launchd.sh` extended to
  install/remove the 76/77 entries idempotently.
- `engine/onboard/capabilities.json` `scheduled-maint` updated: accept/hints
  include 76/77; notes optional cloud/OSS offload → issue #16.
- `agents/README.md` updated: refine/compact are default-on local crons; cloud
  routine setup moved to an "optional offload" section.

## [0.1.0] - 2026-06-19

The first public release of the nervepack engine.

### Added
- Engine and content seam (`NP_CONTENT_DIR`). The harness runs against a user-supplied
  content root, defaulting to the repo root for backward compatibility.
- Host-neutral onboarding contract (`engine/onboard/`). `capabilities.json`, per-host
  adapters, the `np-doctor.sh` verifier, and the `np-core-onboard` skill.
- Backend-neutral LLM seam (`np-llm.sh`, `NP_LLM_BACKEND`: claude, goose, ollama, custom).
- MCP server (`engine/setup/np-mcp-server.py`, `engine/bin/nervepack-mcp`) that exposes
  nervepack's knowledge to any MCP-speaking client.
- Feature-toggle system (`engine/setup/toggles.conf`). Every runtime feature is
  on/off-able.
- Core skills (`np-core-*`) and workflow agents (`np-flow-*`).
- The performance dashboard and the session evaluator.
- Stranger-facing docs: `docs/GETTING-STARTED.md` (a first-time-user walkthrough) and
  `engine/onboard/MCP.md` (the MCP distribution reference — config block, tool list, and
  write-gating).
- Pre-publish snapshot gate (`publish/np-publish-snapshot.sh` + `publish/PUBLISH.md`).
  Exports a single git ref to a history-free tree, scans it, and refuses if anything is
  found. It never pushes. The public release stays a deliberate, human-gated step.
- LAN-IP (RFC1918) rule in `np-publish-scan.py`. Bare private addresses (a real home or
  office box) are now blocked. Loopback (`127.0.0.1`) and doc/public ranges are not.

### Changed
- Design specs and plans now live in the content overlay
  (`$NP_CONTENT_DIR/docs/superpowers/{specs,plans}/`), not the engine. The engine
  carries no `docs/` tree, and a public engine-only clone no longer ships personal
  brainstorm output.
- `np-architecture-freshness.sh` checks the engine's own toggle/feature catalog only.
  The design-spec cross-check is now opt-in through `ARCH_SPECS_DIR` rather than
  scanning the engine tree, since specs are content.
- README de-personalized for an outside reader; the new-machine bringup steps moved into
  `docs/GETTING-STARTED.md`.

### Removed
- The `starter-content/` template. It's replaced by the standalone
  `nervepack-content-example` repo, a filled-in overlay with one worked file in every
  layer (skills, sources, wiki, episodic, playbooks, strategies, metrics, specs).

[Unreleased]: https://github.com/pat-browne/nervepack/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/pat-browne/nervepack/releases/tag/v0.1.0
