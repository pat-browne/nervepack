---
name: np-core-graduate
description: Use when promoting an existing nervepack SKILL.md UP the content-overlay stack — personal → team → org (never the engine repo). Triggers — "graduate this skill to the team layer", "promote np-kb-* to the org overlay", "share this skill with the team/org", "move this skill up a layer". Not for lesson→skill promotion (that is [[np-core-contribute]]).
---

# Graduating a skill up the overlay stack

## Overview

**Graduation moves an existing `SKILL.md` up the content-overlay stack** (personal →
team → org) so a wider, shared audience inherits it. It is **not** a file copy — because
skills merge **override-only**, the moment a team copy exists it *fully shadows the lower
copy for you too*, so the source's fate must be decided deliberately.

**Scope guard.** Target is a **content overlay only** (`$NP_TEAM_DIR` tiers). **Never
graduate into the engine repo** — engine holds generic PII-clean `np-core-*`/`np-flow-*`
machinery only. This is *not* the lesson→skill (authority-axis) promotion — that is
[[np-core-contribute]]. This skill orchestrates existing tools; it adds no new machinery.

## When to use

- "Graduate / promote / share this skill up to the team (or org) layer."
- A personal `np-kb-*` / `np-env-*` skill has proven broadly useful and should be shared.
- A skill flagged in the dashboard's graduation-candidates panel is ready to promote.

**Do not use for:** promoting a *lesson* into a skill ([[np-core-contribute]]); anything
bound for the engine repo.

## The flow (safety-first — nothing leaves the source until the target is confirmed serving)

Run these **in order**. Every gate is confirmed with the user, not auto-applied.
Full commands + exact checks: `references/graduation-checklist.md`.

1. **Resolve the target layer.** Get the team tiers via
   `np_content.team_dir()` / `team_dirs()` (`engine/nervepack_engine/np_content.py`).
   - **None configured → STOP.** There is nowhere to graduate to. Do **not** fabricate a
     `team-dir`; standing up a team overlay (shared repo + governance/CI + everyone's
     config) is a team decision. Report the prerequisites and halt.
   - **Multiple tiers (squad, division, org)** → pick by *audience*, confirm with the
     user. Never default to the broadest.

2. **Suitability / de-personalization gate — the key judgment step.** personal→team is a
   *rewrite*, not a move. If the skill encodes personal identity (a person's name,
   personal absolute paths, tokens/brand tied to one person, `[[links]]` into
   personal-only skills), either **don't graduate it** (a personal aesthetic isn't a team
   asset) or **graduate a de-personalized fork** with a team-neutral `name`/`description`
   and only content the team actually shares. Decide this before touching the target.

3. **Convention + structure checks (interactive).** Move the **whole directory** incl.
   `references/`. Verify `dirname == frontmatter name`; valid `np-<tier>-<name>` (re-tier
   if the destination changes the right tier); `name`+`description` present; body under
   **8 KB** (`np_skill_budget.py`); `references/` intact.

4. **Pre-share safeguards (BLOCKING — a team overlay has no engine pii-guard).**
   - **PII / personal-path scrub** by hand + `publish/np-publish-scan.py <staged-dir>`.
   - **Dangling `[[link]]` audit:** links into personal-only skills break for teammates →
     inline the fact, drop the pointer, or co-graduate the dependency. Never ship a team
     skill pointing into a private overlay.
   - **Name-collision check** against the merged `$TEAM/INDEX.md` (update vs. abort).

5. **Land it in the target overlay.**
   - Overlay skills need **NO `plugin.json` edit** (that is engine-only); relink alone
     registers them, and relink/index are team-aware.
   - **PR if the team repo has review/CI** → filled-out PR (its `PULL_REQUEST_TEMPLATE`),
     merge on green. **No CI** → clean, company-neutral commit, but **announce first** — a
     new team skill silently overriding everyone's is a surprise. Explicit paths, never
     `git add -A`. No LLM attribution. **Ask before pushing.**

6. **Verify it wins.** Relink + regenerate INDEX
   (`np_link_skills.py`, `np_generate_index.py`); confirm the target copy now serves and
   shadows any local copy; run a fresh-agent application test on the graduated skill
   (no dangling refs, no assumption it can read a private overlay); `np-path-check.py` +
   `cli.py doctor` clean.

7. **Retire the source (default) — via the archive convention.** Once the target copy is
   confirmed serving: `mv skills/<name> archive/<name>` and append a row to
   `archive/MANIFEST.md` (`Retired` date, `Reason` = graduated, `Replaced by` =
   `<layer>:<name>`). **Never `rm`** (history is immutable). Relink to prune the symlink.
   Then clear the `graduation-candidates` flag so it stops nagging.
   - **Opt-in — keep as a deliberate LOCAL OVERRIDE:** the only non-dead reason to keep a
     lower copy. It **must use a different `name`** (e.g. `np-kb-foo-personal`) or it will
     just be shadowed by the team copy.

## Quick reference

| Step | Do | Tool |
|---|---|---|
| Target layer | resolve tiers / stop if none | `np_content.team_dir()` |
| Suitability | de-personalize or don't graduate | judgment + user |
| Structure | whole dir, dirname==name, budget | `np_skill_budget.py` |
| Safeguards | PII scrub, link audit, collision | `np-publish-scan.py`, `$TEAM/INDEX.md` |
| Land | PR if CI else announce+commit | `gh` / `commit-push-pr` |
| Verify | relink, confirm it shadows local | `np_link_skills.py`, `doctor` |
| Retire | archive + MANIFEST row (never rm) | `archive/MANIFEST.md` |

## Common mistakes

- **Copy-up-and-forget.** Leaving the personal copy in place = dead, shadowed code that
  silently drifts (you'll edit it and see nothing change). Archive it, or rename it for a
  deliberate override.
- **Treating it as a file move.** A personal-identity skill (e.g. one person's design
  system) shipped verbatim is wrong for a team. De-personalize or don't graduate.
- **Sharing without a scrub.** The engine's pii-guard does **not** cover a team overlay.
  Scrub personal paths/names by hand before any push.
- **Breaking a teammate's `[[link]]`.** Links into your personal overlay resolve to
  nothing for them. Inline, drop, or co-graduate.
- **Editing `plugin.json` for an overlay skill.** That is engine-only; overlays register
  via relink.
- **Removing the source before the target is verified serving.** Order matters — verify,
  then retire.
