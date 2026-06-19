# Publishing the nervepack engine

How to cut a clean public snapshot of the engine. The goal is simple. The public repo
gets the current engine tree with zero personal data and zero git history, and nothing
about the private cross-machine repo leaks out.

This is a deliberate, irreversible step. Creating or force-updating the public repo
happens only behind an explicit human go-ahead, never from an agent or a cron.

## The pieces

| Piece | Job |
|---|---|
| `np-publish-scan.py` | The rules. Greps a directory for secrets and PII (AWS keys, GitHub tokens, private keys, emails, home paths, the personal site, and RFC1918 LAN IPs). |
| `scan-allowlist.txt` | Vetted false positives only (fake tokens planted in tests). Never real data. |
| `np-publish-snapshot.sh` | The gate. Exports one git ref to a history-free tree and runs the scanner over it. Refuses if anything is found. Does not push. |
| `pii-guard` CI job | The same scanner, run on every push and PR, so residue can never land on the default branch in the first place. |

## Before you publish

1. **Run the gate against what you intend to ship.**
   ```bash
   publish/np-publish-snapshot.sh            # scans HEAD, history-free, gate-only
   ```
   It exports `HEAD` (the committed tree, not your dirty working tree) and scans it.
   Exit 0 means clean. Exit 1 means it found something and printed where.

2. **If it blocks, scrub the residue and commit it.** The gate scans the committed
   ref, so fixing a file in your working tree is not enough. Commit the fix, then
   re-run. Common residue the scanner now catches includes bare LAN IPs (a real home
   or office box address), which the per-push `pii-guard` job historically missed.

3. **Sweep for anything the rules don't know about.** The scanner is pattern-based, so
   it won't catch a novel personal hostname or a machine name. Skim the diff since the
   last publish with your own eyes before the first release.

## Cutting the snapshot

When the gate is green, export the clean tree to a directory you can publish from.

```bash
publish/np-publish-snapshot.sh HEAD /tmp/nervepack-public   # keep the clean export
```

That directory is the engine tree at `HEAD` with no `.git`, so no history travels with
it. From there, publishing is a normal git bootstrap into the public remote.

```bash
cd /tmp/nervepack-public
git init -q && git add -A
git -c commit.gpgsign=false commit -qm "nervepack engine <version>"
gh repo create pat-browne/nervepack --public --source=. --remote=origin --push
```

Use a fresh snapshot for each release rather than pushing the private repo's history.
The private repo keeps its full history (it syncs across machines). The public repo is
a sequence of clean snapshots.

## What the gate does and does not promise

- **Does** guarantee no `.git` history and no uncommitted local noise reaches the
  public artifact, and that the tree passes every rule in `np-publish-scan.py`.
- **Does not** invent rules it doesn't have. It is a backstop, not a substitute for
  the engine staying clean continuously (that is what `pii-guard` on every push is
  for). If you find a new class of residue, add a rule with a test (see
  `engine/setup/tests/publish/test_scan.py`) so the next release can't regress.
