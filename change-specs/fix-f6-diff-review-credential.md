---
id: 0008
status: proposed
date: 2026-08-19
tier: high
blast_radius:
  - .github/workflows/ci.yml
  - engine/setup/tests/docs/test_diff_review.py
  - change-specs/**
---

# 0008: activate the multi-lens diff review in CI (F6 follow-up)

## Context and problem statement

Spec 0006 shipped F6's mechanism fail-open and recorded the credential as the
one remaining step: the job "becomes active only once `CLAUDE_CODE_OAUTH_TOKEN`
is added as a repo secret", "activated by adding one secret rather than by more
code."

That is not what the code does. PR #281 is the first change to need the gate,
and it reported `SKIPPED — model unavailable (no claude CLI/credential
configured)` with every other gate green. Two causes, neither of which a secret
fixes:

1. `np-diff-review.py`'s `model_available()` probes for an executable at
   `~/.local/bin/claude` (or `$CLAUDE_BIN`). `ubuntu-latest` does not ship the
   `claude` CLI, so the probe fails before any credential is consulted.
2. The `Run the multi-lens diff review` step passes only `GITHUB_TOKEN` and
   `HEAD_REF`. Even with the secret set, `CLAUDE_CODE_OAUTH_TOKEN` would never
   reach the process.

So F6's advisory reviewer has never run, on any PR, and the repo's own record
says it is one secret away from running. The gap matters most exactly where the
workflow demands it: a **high**-tier change is supposed to get a second
adversarial lens, and #281 is high tier.

## Considered options

1. **Install the CLI from npm at a pinned version and pass the secret
   explicitly** — Good, because the version is pinned, auditable in the diff,
   and updated deliberately rather than silently. Good, because `CLAUDE_BIN`
   already exists as the documented override, so the install location does not
   have to match a hardcoded home-directory path. Bad, because it adds an npm
   install to a repo that is otherwise stdlib-only and dependency-free.

2. **`curl -fsSL https://claude.ai/install.sh | bash`** — Good, because it lands
   the binary at exactly the `~/.local/bin/claude` path the probe already
   expects, with no `CLAUDE_BIN` needed. Bad, because it pipes a remote script
   into a shell inside a job that is about to hold a real credential, and the
   content is unpinned and unreviewable at merge time. Rejected: convenience
   does not justify it in the one job that handles a token.

3. **Change `model_available()` to trust the credential alone** — Good, because
   it is the smallest diff. Bad, because the probe is not wrong; a credential
   with no CLI still cannot run a review, and the resulting failure would be a
   confusing runtime error instead of a clean SKIPPED. Rejected.

## Decision

We will install the `claude` CLI in the `diff-review` job from npm at a pinned
version, set `CLAUDE_BIN` to its resolved path, and pass
`CLAUDE_CODE_OAUTH_TOKEN` into the review step from repo secrets.

The job keeps its fail-open posture unchanged. When the secret is absent — which
is the state on every fork PR, since GitHub withholds secrets from them — the
review still reports `SKIPPED` and the PR still goes green. This change removes
two bugs that made the skip unconditional; it does not make the gate blocking,
and it does not make it required.

Chosen option: "Install from npm at a pinned version", because the one job that
handles a real credential is the wrong place to execute an unpinned remote
script, and `CLAUDE_BIN` already exists precisely so the install path is not
load-bearing.

## Non-goals

**Promoting the gate to blocking or required.** Every measured argument in spec
0006 still holds: LLM review precision is 50–85%, the largest rejection category
is missing project context, and the reviewer posts with `event: COMMENT` at the
API level. This change makes an advisory reviewer run. It stays advisory.

**Auto-updating the pinned CLI version.** A floating version would silently
change the reviewer's behavior between two runs of the same PR, which destroys
the `rules_sha` pinning F4 exists to provide. Bumping it is a deliberate commit.

**Provisioning the secret.** Only the repo owner can mint an OAuth token and
store it. This change makes the wiring correct so that adding the secret has the
effect spec 0006 already claimed it would.

## Cross-cutting concerns

- **Security:** this job now holds a real Anthropic credential while running
  code checked out from a pull request head. For a same-repo branch that is
  self-inflicted and no worse than running the branch locally. For a **fork**
  PR, GitHub does not supply secrets to `pull_request` jobs at all, so the
  credential is simply absent and the gate skips — the fail-open path is also
  the fork-safety path. The existing `HEAD_REF`-via-`env` discipline is
  preserved verbatim; nothing new is interpolated into a `run:` block.
- **Privacy:** the reviewer sends this repo's diff and a capped excerpt of
  `AGENTS.md` to the model. The engine tree is PII-clean by CI gate, and the
  content overlay is never checked out in CI, so no private layer is exposed.
- **Observability:** unchanged. The job already emits an F4 gate verdict, and a
  real run now reports `PASSED` or `FAILED` with a live `evidence_ref` where it
  previously always reported `SKIPPED`.

## Consequences

- Good, because a high-tier change can finally get the second adversarial lens
  the workflow says it gets.
- Good, because the repo's written record stops overstating what is wired.
- Bad, because CI gains a network install and roughly a minute of job time on
  every PR.
- Bad, because it introduces the repo's first npm dependency in CI, against an
  otherwise dependency-free posture. Confined to one advisory job that is
  already `continue-on-error`.
- Neutral, because behavior is unchanged until the secret exists, and unchanged
  on fork PRs forever.

## Confirmation

- `engine/setup/tests/docs/test_diff_review.py` gains assertions that the
  `diff-review` job installs the CLI, pins a version, sets `CLAUDE_BIN`, and
  passes `CLAUDE_CODE_OAUTH_TOKEN` — a parse of `ci.yml`, so it fails if a
  future edit drops any of the three.
- The live proof is PR #281's re-run: its `diff-review` verdict must change from
  `SKIPPED` to a real verdict with a populated `evidence_ref`. Until that is
  observed, this change is unverified, and no completion claim is made from the
  YAML alone.

## Rollback

1. Revert this commit. The job returns to reporting `SKIPPED`, which is its
   current behavior, and nothing else depends on it.
2. Faster, no revert: delete the `CLAUDE_CODE_OAUTH_TOKEN` secret. The wiring
   stays correct and the gate returns to fail-open skip on the next run.

## Deviations

<Append here when implementation leaves the declared blast radius. Each entry:
date, what was touched outside blast_radius, and the one-line reason. Never
delete a prior entry.>
