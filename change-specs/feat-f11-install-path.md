---
id: 0014
status: proposed
date: 2026-08-20
tier: high
blast_radius:
  - engine/setup/hooks.manifest
  - engine/nervepack_engine/np_hook.py
  - engine/setup/tests/nervepack_engine/test_np_hook.py
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0014: stop assuming the install path in hook registration (F11, slice 1)

## Context and problem statement

Criterion 07 grades Strong with one acknowledged constraint: `~/Code/nervepack`
is assumed across setup scripts and skill cross-references. Surveying that
constraint before building changed what this change should be.

**The criterion's first acceptance item is already met.** There is no
machine-specific absolute path anywhere in the tree. The only occurrences of the
maintainer's home directory, and of the macOS home prefix, are inside
`publish/np-publish-scan.py`'s own detection patterns and their tests, which is
where they belong — and the `pii-guard` CI job already fails the build if one
appears elsewhere. That is an enforced property, not a hopeful one.

Enforced firmly enough that it caught this document. The sentence above
originally spelled both paths out while explaining that they appear nowhere but
the scanner, and `pii-guard` failed the build for it. The gate is right: a
literal home path in a committed file is what it exists to catch, and this repo
is meant to go public. Intent is not a category the scanner has, and should not
be.

**The core already resolves its own root correctly.** `np_paths` computes
`REPO_ROOT` from its own file location and never reads `$HOME`.
`np_link_skills.py` says so explicitly in its docstring: "never an unconditional
`$HOME/Code/nervepack`".

So the 40 files mentioning `~/Code/nervepack` split into two very different
piles, and only one of them is a bug:

- **25 markdown files** — documentation examples telling a reader where the
  engine lives on the author's machine. Wrong for a reader who installed
  elsewhere, but inert.
- **`engine/setup/hooks.manifest`, 26 rows** — executable. Every row carried
  `~/Code/nervepack` literally, and `read_manifest` passed it verbatim into
  `~/.claude/settings.json`.

That last one is the actual defect, and it is worse than it looks. **Install the
engine anywhere else and all 26 hooks register pointing at a directory that does
not exist.** Hooks fail open by ARCHITECTURE invariant 1, so nothing errors, no
check goes red, and no message appears. The entire lifecycle — sync, capture,
recall, every gate that runs in-session — would silently do nothing, on a machine
whose owner had no reason to suspect it.

Verified live before writing this: all 26 commands in this machine's
`settings.json` carry the literal path.

## Decision

We will put a `{NP_DIR}` token in the manifest and substitute it in
`read_manifest`, using the root `np_paths` already resolves.

Substitution happens at **read** rather than at registration, so every consumer
of `read_manifest` — the installer, the doctor's drift check, the tests — sees
the same string that lands in `settings.json`. Two places doing this would
eventually disagree about one row, and the disagreement would present as a hook
that reinstalls itself on every sync.

## The worktree correction, found by testing rather than by reasoning

Running the substitution from `.worktrees/f11-install-path` resolved the root to
the worktree, which is technically correct and operationally a trap: registering
from a feature worktree would write 26 commands pointing into it, and the next
`git worktree remove` would leave every hook on the machine pointing at a deleted
directory. Silently, because hooks fail open.

`main_worktree_root()` corrects for it. A linked worktree's `.git` is a *file*
containing `gitdir: <main>/.git/worktrees/<name>`; three levels up is the main
checkout. A normal checkout, or anything that is not a checkout at all, is
returned unchanged — this is a best-effort correction, never a precondition.

This did not exist in the design. It exists because the first real run of the new
code produced a path that looked right and was not.

## The check for platform assumptions had a platform assumption

The first version validated absoluteness with `os.path.isabs`. That passed
locally and failed the Windows lane, because **Python 3.13 changed
`ntpath.isabs` to require a drive letter**, so `/opt/nervepack` is absolute on
Linux and not absolute on Windows. Local Python here is 3.12, where the old
behaviour still holds, so the assumption was invisible on two axes at once —
platform and interpreter version.

Absoluteness is now judged from the string, by one regex, identically
everywhere. That is the correct semantics regardless of the bug: the check is
about a string that will be embedded in a bash command on the **target**
machine, so it must not consult the machine running the check at all.

Worth recording rather than quietly fixing. This is a change whose entire purpose
is removing an assumption about where things live, and it shipped its first
draft with an assumption about where it was running.

## Considered options

1. **A token substituted at manifest-read time** (chosen) — Good, because the
   manifest stays declarative and greppable, and one function owns the
   substitution. Bad, because a token in a command string is one more thing to
   know when reading the file, which the header now explains.
2. **Resolve at hook runtime instead**, registering a command that discovers its
   own root — Good, because settings.json would then survive the engine being
   moved. Bad, and disqualifying, because it needs a shell prelude in all 26
   commands, and every one of them runs on the session's critical path.
3. **Leave it and document the assumption** — this is the status quo the
   criterion calls a constraint. Rejected because the failure is silent.

## Non-goals — the rest of #257

This is one slice. Named explicitly so the remainder is tracked rather than
assumed done:

- **The 25 markdown references.** Documentation, inert, and a separate change.
- **A host-adapter directory.** #257 asks that Claude-Code-specific hook and
  cron wiring move behind an adapter so the core carries no host types. Real
  work, and orthogonal to this.
- **The grep-based pre-commit check** for `/Users/`, `/home/`, `C:\`. Worth
  having, but `pii-guard` already enforces the same property in CI, so it is a
  convenience rather than a gap.
- **XDG resolution and its contested macOS behaviour.** Untouched here.
- **A CI clean-clone install from another path.** The right proof for this
  change, and it needs a fixture this slice does not build.

## Cross-cutting concerns

**Security.** None added. The substituted value comes from the engine's own file
location, never from the environment or from user input.

**Privacy.** The resolved root contains the operating user's home directory on
most installs, and it lands in `~/.claude/settings.json` — which is exactly where
it landed before, expanded from `~`.

**Observability.** A machine that already registered the literal path self-heals:
`sync` re-runs `install-hooks` on a fast-forward, and registration replaces rows
by event.

**Portability.** The substituted path is normalised to forward slashes. These
commands route through bash on a Git-bash host, where a backslash is an escape
rather than a separator, and Git-bash accepts `C:/Users/...`. That is S1075's
often-missed sub-rule in practice: the separator is not chosen per platform, it
is normalised to the one form the consumer understands.

## Consequences

**Good.** A clone at `/opt/nervepack` or `D:\src\nervepack` registers working
hooks. The silent-total-failure mode is gone.

**Bad.** The manifest is no longer copy-pasteable into a shell as-is. Anyone
debugging a row has to know what `{NP_DIR}` means, which the header now says.

**Neutral.** Hook commands in `settings.json` grow by the length of the absolute
path, since `~` is no longer doing that compression.

## Confirmation

- `test_np_hook.py` asserts no non-comment manifest row contains
  `Code/nervepack`, that every engine row uses the token, that the token is gone
  after a read, that `/opt/nervepack` and `D:\src\nervepack` both substitute
  correctly, and that the Windows form normalises to forward slashes.
- Four more assert the worktree correction: a linked worktree resolves to its
  main checkout, and a normal checkout, a non-checkout, and a `.git` file that is
  not a `gitdir:` pointer are all returned unchanged.
- The Windows CI lane exercises registration end-to-end.

## Rollback

`git revert` this commit, then re-register:

```bash
python3 engine/nervepack_engine/cli.py setup install-hooks
```

Registration replaces rows by event, so the literal paths come back in one step
and no settings.json surgery is needed. The change is confined to the manifest
and one function; nothing persists a substituted command anywhere except
`settings.json`, which that command rewrites.

Verify with:

```bash
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/settings.json')));print(sum(1 for e in d['hooks'].values() for r in e for h in r['hooks'] if 'nervepack' in h['command']))"
```

26 is the expected count either way — what changes is what the commands point at.
