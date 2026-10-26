# Stack facts go to the wiki

Code work in a tech stack teaches facts about the stack itself. Skills hold
rules and lessons hold failures. Neither holds what the stack does. The wiki
does, so the next project in that stack starts from it.

## Two paths, no new job

| Path | Runs | Writes |
|---|---|---|
| Sweep (this page) | In the session, at a milestone | `wiki/` directly, through [[np-core-contribute]] |
| Pipeline | Every session, including dead ones | `memory/stack-facts/<stack>.md`, a staging layer |

The pipeline rides jobs that already exist. Nothing new is scheduled.

- The capture hook asks for `stack_facts[]` in the same call that returns
  `struggles[]` and `strategies[]`.
- The back-capture sweep re-runs that call on a session that ended without
  warning.
- `episodic-maintain` §5c stages the facts and flags stacks ready for the wiki.

The sweep is the attended fast path. The pipeline is the backstop.

A human promotes a staged fact through [[np-core-contribute]]. Unattended runs
never write to `wiki/`.

## The sweep (run after code work, before the final report)

1. Name every stack the session touched: language, framework, cloud service,
   database, build tool, platform SDK.
2. For each, ask: what did I verify about how it behaves that I did not know,
   or had to look up? Count only facts with evidence from this session.
3. Save each one to that stack's wiki topic, as below.

Nothing new for a stack? Say so in the `Captured:` line. Do not pad the page.

A fact the sweep already saved is skipped later. `episodic-maintain` greps the
wiki before it stages anything.

## Wiki, skill or lesson?

| Learning | Goes to |
|---|---|
| How the stack behaves: API shape, default, limit, version constraint, config format, error cause | **wiki** |
| What to prefer or avoid when acting | skill, linked to the wiki fact |
| A failed approach and its recovery | lesson (distilled by episodic-maintain) |
| Detail of one project | that repo's `CLAUDE.md` |

A gotcha often splits. The mechanism and root cause go to the wiki. The rule
("pin X to 3.x") goes to the skill with a `[[wikilink]]` to the mechanism.

## Where it lands

Resolve the path with `cli.py layout route knowledge`. Never invent a directory.

1. Search first: `grep -ril <stack> "$CONTENT"/wiki/topics "$CONTENT"/wiki/concepts "$CONTENT"/memory/stack-facts`.
2. Topic exists: add the fact to its synthesis page. Vendor docs go in a
   co-located `kind: reference` page with the URL and version.
3. No topic: create `wiki/topics/<stack>/<stack>.md` with `kind: topic`, and
   always write the synthesis page.
4. Promoting a staged entry: move it into the wiki page and delete it from the
   staging file in the same commit.
5. Delegate the write to [[np-core-contribute]] (kind `knowledge`), which owns
   the branch, the index and the commit.

A concept page fits only when the subject owns no reference sources.

## Shape of an entry

Three lines beat a paragraph:

```text
- **Claim.** One sentence stating the behavior.
  Verified: <stack> <version>, <date>. Evidence: <command, output or file:line>.
  See also: [[related-skill-or-page]]
```

## Do not

- Copy documentation. Link the source and record only what you verified.
- Record a guess. Unverified means it stays out.
- Put a secret, token or hostname in a page.
- Start a second page for a stack that already has a topic.
