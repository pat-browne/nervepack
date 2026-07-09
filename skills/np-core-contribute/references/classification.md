# Classification rules — which layer, which tree

Depth for the "Classify by layer first" pointer in the skill body.

## Classify by LAYER before you capture (anti-drawer rule)

Decide *what kind of thing* the learning is **before** picking a file:

- **Behavioral / how-to** (a reusable technique, rule, or capability) → a **skill**
  (new one if it's worth a name — not a paragraph buried elsewhere).
- **Knowledge** (what a thing is, how a build works, a synthesized topic) → the
  **wiki** (`concepts/` or `topics/`).
- **Deferred work** (not done yet, revisit on a trigger) → a **roadmap** row only.

A roadmap (incl. `references/roadmap.md`) is **deferred-work tracking, not a
knowledge drawer** — even for a roadmap item, the deferred line goes in the
roadmap and the durable how-to/detail goes in a skill or wiki page, cross-linked.
(Miss: the Walter persona how-to was dumped in the local-llm roadmap, then split
out to [[np-kb-persona-llm-agents]] + wiki. Classify first, skip the rework.)

## Skills vs sources — which layer?

- **Skill** = "how to act / what's installed / what to prefer." Behavioral
  guidance, opinion, choice. User-specific.
- **Source** = "what the spec says." Official reference content, version-
  pinned, defer-first when answering. Not opinionated — quotes/excerpts
  the canonical document.
- Cross-link them in a `wiki/` synthesis page when the entity (e.g. Rust)
  has both skill content *and* source content.

## Cross-tree linking — look before you author

Durable docs favor links over duplication. Beyond the same-topic dup check in
the skill's step 2, do a **lightweight cross-tree lookup**: grep the merged
`INDEX.md` / `wiki/` / `sources/` for the subject matter you are documenting.
If a related node lives in a *different* tree — even with zero duplication
risk — add a `[[wikilink]]` (or path) so a future agent can navigate to it.
Depth lives in one place and is linked from everywhere else, never copied
(see `docs/ARCHITECTURE.md`).
