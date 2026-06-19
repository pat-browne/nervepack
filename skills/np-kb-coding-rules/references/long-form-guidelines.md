> Long-form coding guidelines (origin credited in NOTICE). Summary lives in the parent SKILL.md.

# Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes, derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

# Rule 12 — Path-move consumer audit (the three blind spots)

When you relocate something other code reads by path — a config dir, a content
root, a file, or a directory that becomes a symlink — the regression is almost
never the move itself. It's a consumer left pointing at the old location. So the
work is: enumerate **every** reader of that path and fix each one, with a
regression test per fix (Rules 5 and 8). The readers that get missed cluster in
three recurring blind spots:

1. **Code in a different language than the shared resolver.** The canonical
   path-resolver lives in one language (e.g. a bash helper); a consumer written
   in another (e.g. a Python script) reimplements the default by hardcoding the
   old location instead of calling the resolver. Grep across *all* languages, not
   just the resolver's. Fix: have it resolve via the same precedence (env →
   config → fallback), so future moves need no second edit.

2. **Security path-guards that `realpath`-canonicalize.** A guard that resolves a
   request to its real path and requires it under an allowed root will *reject* a
   directory that the move turned into a symlink pointing outside that root —
   treating a legitimate file as path traversal. Fix: add the canonical symlink
   target as a second allowed root; keep the canonicalize-then-prefix-check so
   `../` escaping *both* roots is still refused. Verify with a test that the
   symlinked file serves AND that `../` through it is still blocked.

3. **Generators that write into a guarded publishable surface.** An artifact
   generator (index, manifest, catalog) that merges a personal/overlay view and
   writes it into a surface a guard polices (e.g. a secret/PII scanner on the
   public-facing tree) will leak personal data and turn the guard red. Fix: emit
   the public-only view to the guarded surface and the merged/personal view to a
   private/local location.

Worked example: nervepack's engine/content overlay split. `build.py` hit (1)
(hardcoded engine `playbooks/`/`strategies/` defaults); `np-dashboard-server.py`
hit (2) (the symlinked `dashboard/data` resolved outside the served root → every
`/data/*` 404'd → empty dashboard); `60-generate-index.sh` hit (3) (the committed
engine `INDEX.md` carried overlay skills → `pii-guard` CI red). All three passed
their own narrow tests before the move; the move is what exposed them.
