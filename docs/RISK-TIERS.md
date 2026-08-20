# Risk tiers

`engine/setup/risk-tiers.json` maps path globs to a risk tier. `spec-guard` reads
it to decide whether a change needs a change spec at all, and whether the tier
that spec declares is high enough for what the diff actually touches.

## This taxonomy is a synthesis, not a citation

**No published standard enumerates high-risk code paths.** CIS says "extra
sensitive code or configuration" without defining it. Google's *Building Secure
and Reliable Systems* says "safety implications". SLSA says "security-relevant
properties". Every organization invents its own list, and the one in
`risk-tiers.json` is ours.

Do not cite it as though it came from a standard. The sentence also ships inside
the JSON itself, and a test asserts it stays there, because a list like this
reads as authoritative once it is in a file.

## The three tiers

| Tier | Means | Spec required | Gate consequence |
|---|---|---|---|
| **standard** | Pre-authorized class: docs, wiki, skill references, comments, test-only | No | Deterministic gates only. Auto-merge eligible (decided by `tier-gate`, acted on by #255). |
| **normal** | Everything not otherwise matched. The default. | Yes | Full gate set. A human merges. |
| **high** | Hooks, crons, CI config, installers, credential paths, PII and publish guards, layer path resolution, and the tiering machinery itself | Yes, plus a rollback plan | Full gate set plus a second adversarial lens. Never auto-merges. |

`standard` is a real authorization, not a shortcut. ITIL 4 grants authorization
once to a documented procedure with a known risk profile and a defined rollback,
and it explicitly permits an automated CI/CD mechanism to hold the change-authority
role. With one maintainer, that is the honest model: the deterministic gates are
the change authority for this class, and they were authorized when the class was
defined.

## Last match wins

Precedence mirrors **CODEOWNERS**: the *last* matching rule in the `rules` array
decides, not the most specific one.

```json
{"glob": "src/**",      "tier": "standard"},
{"glob": "src/auth/**", "tier": "high"}
```

`src/auth/login.py` resolves to **high**. Swap the two lines and it resolves to
**standard**.

This is the opposite of most people's intuition, so:

- **Standard-tier globs go first. High-tier globs go last.**
- Appending a broad standard glob at the bottom silently downgrades everything it
  matches. That is the file's main foreseeable mis-edit, and
  `test_risk_tiers.py` asserts no standard rule ever appears after a high one.

Specificity-based precedence was considered and rejected: "specific" has to be
defined (segment count? wildcard count?), every definition has surprising cases,
and CODEOWNERS chose ordering over specificity to avoid exactly that. A
tier-keyed object (`{"high": [...], "normal": [...]}`) was rejected outright —
JSON object key order carries no semantic guarantee, so last-match-wins cannot be
expressed in one at all.

## Globs already cross directory separators

Matching uses `fnmatch`, whose `*` is **not** path-aware — it translates to regex
`.*` and already crosses `/`. So `docs/**` and `docs/*` behave identically, and
any wildcard reaches arbitrary depth. The rules are written with `**` for
readability only.

## The registry classifies itself

`risk-tiers.json`, `np_risk_tiers.py`, `np-spec-guard.py`, and
`np_change_spec.py` are all **high** tier rules in the shipped file.

Without that, the policy governing how much scrutiny every change receives could
be rewritten in a standard-tier diff — one needing no spec, no declared tier, and
no review. That is a privilege escalation using the tiering mechanism as its own
vector. A test pins it.

## The ratchet turns one way

Discovering that a "standard" change touches a hook **upgrades** it to high.
Nothing downgrades mid-task.

`spec-guard` enforces the *outcome*: a spec declaring a tier lower than its paths
require fails, naming the paths that forced the higher tier. Over-declaring
always passes.

**CI cannot enforce the rest of the ratchet**, and this document will not pretend
otherwise. CI sees one diff, not a task's history, so it cannot know a change was
called `standard` an hour ago and quietly relabelled. That half is a process rule
in the `np-flow-develop` skill, held by the person doing the work.

## What reads a tier

Three consumers, all reading this one registry through `np_risk_tiers`.

| Consumer | Uses the tier to decide |
|---|---|
| `engine/setup/np-spec-guard.py` (`spec-guard` CI job) | whether the change needs a spec at all, and whether the tier the spec declares is high enough for the paths the diff touches |
| `engine/setup/np-tier-gate.py` (`tier-gate` CI job) | which gate verdicts must be PASSED, whether the spec needs a populated `## Rollback`, and whether the adversarial lens must have run |
| `engine/setup/np_codeowners.py` | which globs get written into `.github/CODEOWNERS` as the declared high-risk paths |

`.github/CODEOWNERS` is generated, never hand-edited, and a test fails when it
drifts from this file. It declares and routes. It does not gate.

The full requirement table per tier, and the reason every pull request runs the
same jobs rather than a tier-specific subset, live in
[BRANCH-PROTECTION.md](BRANCH-PROTECTION.md).

## Changing the registry

Editing it is a high-tier change: it needs its own change spec with `tier: high`
and a rollback plan. That is deliberate. If adding a glob were cheap, the cheapest
path through any gate would be to widen the standard tier until the gate stopped
firing.

Related: `change-specs/README.md` (the spec artifact), `docs/ARCHITECTURE.md`
invariant 1 (blocking hooks), and change spec `0009` for the design argument.
