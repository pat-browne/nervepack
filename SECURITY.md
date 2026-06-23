# Security Policy

Thanks for helping keep nervepack and the people who run it safe.

## Reporting a vulnerability

**Please do not open a public issue for security problems.** Public issues are
visible to everyone, including before a fix exists.

Report privately through GitHub's
[private vulnerability reporting](https://github.com/pat-browne/nervepack/security/advisories/new)
on this repository (the **Security → Report a vulnerability** button). That
opens a confidential thread with the maintainer.

When you report, please include:

- What the issue is and the impact you think it has.
- Steps to reproduce, or a proof of concept.
- The commit SHA or release you saw it on.

You can expect an acknowledgement within a few days. Because nervepack is a
small, single-maintainer project, please be patient with timelines, and we'll
keep you posted as a fix lands.

## Scope

nervepack is an engine that wires hooks, crons, and an MCP server into an AI
coding host, and runs shell scripts and headless `claude -p` calls on your
machine. The things we care most about here:

- **Code execution and injection** in the hooks, setup scripts, the MCP server,
  or the headless model calls.
- **Secret or PII leakage.** The engine is meant to be published with no personal
  data in it; the `pii-guard` CI job (`publish/np-publish-scan.py`) enforces that
  on every push and PR. A way to get a secret or PII committed past that guard,
  or leaked into logs, the dashboard, or a model prompt, is in scope.
- **Supply-chain risk** in the GitHub Actions workflows or the few pinned Python
  test dependencies.

Out of scope: vulnerabilities in your **content overlay** (your private data
lives in a separate repo, not here), and issues that require an attacker to
already have write access to your machine or your `~/.config/nervepack`.

## Handling secrets

If your report needs to reference a real secret or piece of PII to be
reproducible, **redact it** before sending, or describe it abstractly. Do not
paste live credentials into the advisory thread.
