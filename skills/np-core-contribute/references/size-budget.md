# Skill size budget — keeping SKILL.md lean

A skill's whole body loads into context every time it's invoked, so an
overweight skill is a recurring token tax on every session that touches it.

## Targets

- **Soft cap:** ~6 KB (~1.5k tokens) per `SKILL.md` — the authoring target you write to.
- **Hard limit:** 8 KB — enforced daily by `engine/setup/75-skill-maintain.sh`
  (auto-splits bodies over the limit into `references/` behind a validate-or-abort gate).

## When the body exceeds the soft cap

1. **Tighten first.** Cut restated context, worked examples that don't change the
   rule, and prose that a one-line rule + a code block already convey.
2. **Then split, don't sprawl.** Move long reference material (full checklists,
   multi-step recipes, large code samples) into `skills/<name>/references/*.md`
   and add a one-line pointer in the body.
   - References are read **on demand** — they cost nothing until actually needed,
     unlike the always-loaded body.
   - The body carries the *decision* (what to do, the rule, the trigger).
   - The reference carries the *detail* (how, the long worked example).

## Checking sizes

```bash
find skills -name SKILL.md -exec wc -c {} +
```

Trim opportunistically when you're already editing a skill — don't do a
risky bulk split blind.
