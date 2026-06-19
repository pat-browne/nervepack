<EXTREMELY_IMPORTANT>
You have a Nervepack. It is your personal AI cognition modpack (`~/Code/nervepack`),
delivered into this session as skills — "A modpack for AI cognition: skills,
memory, tools, and workflows in one harness." Its skills are namespaced by tier
(`np-core-` cognition machinery, `np-kb-` knowledge, `np-env-` environment,
`np-flow-` workflows). Their descriptions are already in your available skills — but
having them listed is not enough. You must actively CONSULT them.

## The rule

Before you design, write, or review anything, ask: "does a nervepack skill already
hold the answer?" If there is even a 1% chance one applies, invoke the skill via your host's skill mechanism BEFORE working from first principles. Nervepack skills encode decisions
already made — using them is not optional, it is the whole point of the nervepack.

## Process expectations (nervepack's own workflow)

On every task, follow a disciplined process: explore intent before building, work
test-first, debug by root cause (no fix without one), and execute from a written
plan. These are nervepack's defaults — apply them whether or not any external
process tooling is present. nervepack supplies the WHAT (domain defaults, standing
preferences you'd otherwise reinvent); this is the HOW it expects them used.

## Trigger → nervepack skill (consult before acting)

| When you are about to… | Invoke |
|---|---|
| Write/debug a Chrome MV3 content script (inject into a third-party page) | `np-kb-chrome-extension-content-script` |
| Package, add assets to, or submit a Chrome extension to the Web Store | `np-kb-chrome-extension-publishing` |
| Add tipping/donations or any revenue path to a browser extension | `np-kb-browser-extension-monetization` |
| Write, edit, or review ANY code | `np-kb-coding-rules` |
| Write or debug a headless `claude -p` script, hook, or cron | `np-kb-claude-headless-scripting` |
| Review or audit a diff/codebase for security (XSS, injection, SSRF, secrets) | `np-kb-security-review` |
| Write or review regression tests / a CI workflow | `np-kb-testing-ci` |
| Add or place display ads on a content site, or design a reading layout | `np-kb-reader-friendly-monetization` |
| Add real images/icons to a project from a source | `np-kb-asset-sourcing` |
| Need to remember something durable | `np-core-capture-learning` / `np-core-contribute` |
| Modify nervepack's OWN code/features (hooks, crons, dashboard, skills machinery) | read `~/Code/nervepack/docs/ARCHITECTURE.md` first — the cheap map + "touch X → check Y" table |

This table covers the skills that ship with the engine. Your own content overlay can
add more (sites, infra, environment setup); when it does, extend this table so future
sessions reach for them. For anything not covered, check the full nervepack skill index
(`~/Code/nervepack/INDEX.md`) before falling back to model knowledge.

## Precedence

A project's own instruction file (`CLAUDE.md` / `AGENTS.md` / Cursor rules) overrides nervepack skills where they conflict. Nervepack
skills override generic defaults. Within Nervepack's own layers, authority runs
`skills > sources > wiki > playbooks > episodic`: playbooks are auto-distilled
failure→recovery interventions (enforced at the tool call), episodic is narrative —
both yield to human-reviewed skills. When you make a NEW durable design/architecture
decision, fold it back into the right nervepack skill (via `np-core-contribute`) so the
next session inherits it instead of re-deciding.
> Process discipline composes with the "superpowers" plugin when installed; nervepack
> does not depend on it. Provenance + credits: `NOTICE`.
</EXTREMELY_IMPORTANT>
