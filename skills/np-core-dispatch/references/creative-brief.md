# Briefing an agent for creative / editorial work

Implementation work is verifiable against tests. Copy, voice, and design work is not —
so the brief has to carry the judgment the reviewer would otherwise supply. A brief that
names its decision points becomes a contract the agent can execute without redirection.

Four things every creative dispatch must state:

1. **What to say.** The messaging frame and the specific claims that are in bounds.
   Not "make it better" — the argument you want made.

2. **What may be edited — and what may not.** This is the one that bites. Sites and docs
   commonly contain **generated or synced files** that a build step overwrites; editing
   them is wasted work that silently disappears on the next build. Identify the generated
   paths explicitly and fence them off. If you don't know which files are generated, find
   out before dispatching, not after.

3. **Voice and design rules.** Name the skills to invoke rather than describing the voice
   inline — a pointer to the actual rules beats a paraphrase of them.

4. **The publication gate.** Say where it stops: build and preview before pushing, or stop
   before pushing entirely and report. Creative work should get a human look before it is
   public; the gate is what guarantees one.

## Why the fence matters most

The failure is asymmetric. A weak messaging frame produces mediocre copy you can see and
fix. Editing a generated file produces work that looks correct, passes the agent's own
review, and then vanishes — with nothing in the diff to explain why. Ten words fencing
the generated paths costs less than one round of that.

## Pairs with

- The out-of-scope-flag line from the main skill: a well-fenced agent will notice things
  just outside its fence (stale content, a broken link, a doc that contradicts the copy).
  Give it permission to report those instead of fixing or ignoring them.
