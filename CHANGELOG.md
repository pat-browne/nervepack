# Changelog

All notable changes to the nervepack **engine** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims for
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This tracks the reusable engine, so the machinery, skills, onboarding, and MCP surface.
It does not track any individual user's personal content overlay.

## [Unreleased]

### Added
- `76-run-refine.sh` and `77-run-compact.sh`: local cron bodies for the refine
  (frontmatter lint + cross-ref audit) and compact (skill dedup + split proposals)
  agents. Default-on, gated by `maintain.refine` / `maintain.compact` toggles.
  Installed idempotently by `70-install-memory-cron.sh` (Linux) and
  `70-install-memory-launchd.sh` (macOS). Run via `np-llm.sh` agent mode —
  provider-agnostic (claude backend or `NP_LLM_AGENT_CMD`), fail-open.
- `maintain` / `maintain.refine` / `maintain.compact` toggle entries in
  `toggles.conf` (default on).

### Changed
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
