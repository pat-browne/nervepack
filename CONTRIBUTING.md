# Contributing to nervepack

Thanks for taking a look. nervepack is a modpack for AI cognition, the skills, memory,
tools, and workflows that follow you across machines and AI hosts. This guide is about
contributing to the **engine**, the reusable machinery. Read [`README.md`](README.md)
for the overview and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the map before you change
any code.

## Engine vs. content

nervepack keeps the **engine** (the reusable harness, so hooks, crons, the toggle
system, onboarding, the MCP server, the core skills, the workflow agents) separate from
**personal content** (your own skills, notes, and knowledge). The engine reads its
content from a root that `NP_CONTENT_DIR` resolves, defaulting to the repo root when
unset.

Contributions go to the engine. Personal knowledge stays in your own overlay and does
not belong in this repository. So keep your PRs free of personal data, meaning no names,
emails, home paths, private hostnames or IPs, or credentials. There's a CI guard
(`pii-guard`) that enforces this, but please don't make it work for a living.

## Development

nervepack is deliberately dependency-light.

- **Bash** for the hot-path glue, so hooks, session start and end, recall.
- **Python 3, standard library only** for off-hot-path parsing and logic. No `pip
  install`, no virtualenv. Tests use stdlib `unittest`, not pytest, for the same
  reason.

There's no build step. Clone, edit, run the checks below.

### Checks before you open a PR

CI runs a syntax sweep, the regression suite, and the PII guard on every push and pull
request (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). Run the cheap
ones locally first.

```bash
git ls-files '*.py' | xargs -r python3 -m py_compile            # Python syntax
git ls-files '*.sh' | while read -r f; do bash -n "$f"; done    # Bash syntax
bash engine/setup/tests/run-all.sh                              # the whole suite, zero deps
```

If you touched one area, you can run just its tests instead.

```bash
python3 engine/setup/tests/<area>/test_<name>.py     # stdlib unittest
bash    engine/setup/tests/<area>/test_<name>.sh     # bash test
```

## Conventions

- **Simplicity first, and keep changes surgical.** Write the minimum that solves the
  problem. Don't refactor or reformat code next door that you weren't asked to touch.
- **Every new feature is toggleable.** A hook, cron, or managed config has to add a row
  to `engine/setup/toggles.conf` and gate itself with `np_enabled <feature> || exit 0`
  (fail-open). `docs/ARCHITECTURE.md` and the toggle docs cover the why.
- **Add a test for any bug fix or new behavior**, either a stdlib `unittest` or a bash
  test under `engine/setup/tests/`.
- **No AI or LLM attribution** in commits, PR descriptions, or code comments. No
  `Co-Authored-By: <AI>` trailers, no "generated with" lines. Author your work plainly.
  (Agent-instruction files like `CLAUDE.md` are functional config, not attribution, so
  they stay.)

### Commit messages

Use a conventional prefix that matches the area.

```
skill(<name>):   <change>    # a core or flow skill
setup(<step>):   <change>    # a bootstrap or runtime script under engine/setup/
agent(<name>):   <change>    # a workflow-agent prompt under agents/
manual:          <change>    # README, ARCHITECTURE, CLAUDE.md, or docs
```

## License

By contributing, you agree your contributions are licensed under the project's
[Apache License 2.0](LICENSE).
