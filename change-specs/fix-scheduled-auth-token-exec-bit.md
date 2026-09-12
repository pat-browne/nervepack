---
id: 0035
status: proposed
date: 2026-09-11
tier: high
blast_radius:
  - engine/setup/62-install-scheduled-auth-token.sh
  - change-specs/fix-scheduled-auth-token-exec-bit.md
---

# 0035: scheduled-auth-token installer is not executable

## Context and problem statement

`engine/setup/62-install-scheduled-auth-token.sh` ships at mode 644. Its
sibling `58-install-mcp.sh` ships at 755.

`cli.py onboard` runs the file through a shell, so onboarding works. The
walkthrough it prints names the script by bare path. A user who copies that
path gets "permission denied".

This hit a real install on 2026-09-10. The onboard printed the walkthrough. The
bare path failed. The run only worked with a `bash` prefix added by hand.

The file is the one genuinely manual onboarding step. A stumble here lands on
the user at the exact moment the tooling hands over control.

## Considered options

1. `chmod +x` the file.

   Good, because it matches `58-install-mcp.sh` and the printed instruction.
   Neutral, because the mode is the only change.

2. Change the walkthrough to print a `bash` prefix.

   Good, because no mode change is needed. Bad, because the two installers then
   differ for no reason a reader can see.

3. Add a repo-wide mode guard in CI.

   Good, because drift cannot recur. Bad, because it is a larger change than
   the defect warrants. It belongs in its own spec.

## Decision

We will `chmod +x engine/setup/62-install-scheduled-auth-token.sh`.

Chosen option: "chmod +x the file". It matches the sibling installer and the
instruction the onboard already prints.

Option 3 stays open as separate work.

## Non-goals

Auditing modes across the whole repo. Only this file is known to be wrong.

Changing the script's contents. The token flow and its 600-permission write are
untouched.

## Cross-cutting concerns

- Security: the script reads a long-lived OAuth token with hidden input. The
  mode change does not alter that path. The token still lands in a file at 600.
- Privacy: none. No new data is read or written.
- Observability: the doctor already reports `scheduled-auth-token` status.

## Consequences

- Good, because the printed walkthrough now works as written.
- Good, because the two installers agree on mode.
- Neutral, because callers that already use a `bash` prefix keep working.

## Confirmation

`test -x engine/setup/62-install-scheduled-auth-token.sh` exits 0 after this
change. `git ls-files -s engine/setup/62-install-scheduled-auth-token.sh`
reports mode `100755`.

`bash engine/setup/62-install-scheduled-auth-token.sh --status` still prints a
one-word status. Verified as `ok 366` on macOS 13.7.8 on 2026-09-11.

## Rollback

`git revert` the commit, or `chmod -x
engine/setup/62-install-scheduled-auth-token.sh` and commit the mode back.

No state outside the repo changes, so a revert is complete on its own. A token
already stored at `~/.config/nervepack/` is untouched either way.

## Deviations

None.
