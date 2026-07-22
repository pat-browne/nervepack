# Getting started with nervepack

nervepack is a context hub you run across your machines — skills, memory, tools, and
workflows your AI coding assistant reads every session. This is the first-time install.

> **Prerequisite:** an *agentic* host — one that can read/write files and run shell
> commands (Claude Code, Cursor, Codex, Goose, …). A plain chat UI can only consume the
> knowledge as context; it can't self-wire.

## Quick start

The same four steps on Linux, macOS, and Windows. The host **self-wires** — you don't
hand-edit hooks or settings; the onboard does it and proves it with the doctor.

**1. Get the code.**

```bash
git clone https://github.com/pat-browne/nervepack ~/Code/nervepack
```

Git is the only prerequisite for this step. On **Windows, install
[Git for Windows](https://gitforwindows.org) first** — it supplies the `bash` that runs
every nervepack hook and cron.

**2. Install the toolchain** (gh, jq, node, python, go, build tools):

| OS | Command |
|---|---|
| Linux | `python3 ~/Code/nervepack/engine/nervepack_engine/cli.py setup install-apt-baseline` |
| macOS | `python3 ~/Code/nervepack/engine/nervepack_engine/cli.py setup install-brew-baseline` |
| Windows | No installer step — install **Node 20, Python 3, `gh`, and `jq`** by hand (Git for Windows already covers bash). |

The engine runs on **Bash + Python 3** — the baseline above installs Python (`apt` on
Linux, `uv python install` on macOS; install it by hand on Windows), so every engine
script works out of the box. On a Claude host, finish with
`python3 ~/Code/nervepack/engine/nervepack_engine/cli.py setup install-claude-plugins`.

**3. Authenticate GitHub** (so the maintenance jobs can push your content):

```bash
gh auth login    # GitHub.com · HTTPS · login with a browser
```

**4. Onboard the host.** Open your agent in `~/Code/nervepack` and say:

```text
onboard nervepack
```

(On a fresh box there is no slash command yet — `/np-onboard` is itself a nervepack
skill, so it only exists *after* onboarding links the skills. Saying "onboard
nervepack" works from zero because the agent auto-loads this repo's `CLAUDE.md`,
which routes it to the contract. Non-interactive alternative:
`python3 ~/Code/nervepack/engine/nervepack_engine/cli.py onboard` runs the same
wiring directly. Once onboarded, `/np-onboard` is available for re-runs.)

Your agent reads the tool-neutral contract, links the skills, installs the session hooks
and scheduler, writes `~/.config/nervepack/adapter.json`, and runs the doctor until every
MUST capability is green. Verify any time:

```bash
~/Code/nervepack/engine/setup/np-doctor.sh   # per-capability PASS/MISSING; non-zero on a real gap
```

That's the whole install. What differs by OS is handled for you:

| | macOS | Windows |
|---|---|---|
| Toolchain | `cli.py setup install-brew-baseline` | manual (Node · Python · gh · jq) |
| Scheduler backend | launchd LaunchAgents | Windows Task Scheduler |
| Hook execution | native bash | commands auto-wrapped through Git-bash |

On a **non-Claude host**, there's no `CLAUDE.md` auto-load or slash command — point
your agent at the same contract directly:
[`../engine/onboard/ONBOARD.md`](../engine/onboard/ONBOARD.md).

## Going deeper

Everything above gets you running. These child pages cover the optional, heavier setup:

- **[Content & team overlays](CONTENT-OVERLAY.md)** — point the engine at your own
  private skills/memory repo (and an optional shared team overlay). Recommended; without
  it the engine falls back to its own root and you have nowhere personal to grow.
- **[Scheduled maintenance agents](../agents/README.md)** — the crons/routines that
  promote memory, compact skills, and lint. Optional; nervepack works without them.
- **[Onboarding contract](../engine/onboard/ONBOARD.md)** — the tool-neutral capability
  contract for wiring any agentic host by hand.
- **[Bootstrapping over MCP](../engine/onboard/MCP.md)** — after the one `git clone`,
  point any MCP client at the server and a single `nervepack_onboard` call wires the rest.
- **[Architecture](ARCHITECTURE.md)** · **[Features](FEATURES.md)** — how the engine,
  layers, and toggles fit together.

### Sanity-checking paths

The engine and your content overlay live in separate repos, so a script named in a skill
can drift. This catches a stale path before you chase a dead command:

```bash
python3 ~/Code/nervepack/engine/setup/np-path-check.py ~/Code/nervepack ~/Code/nervepack-content
```

A clean run prints `all setup/onboard path references resolve ✓`; any hit names the file,
the line, and the path to fix. The same check runs in CI, so the engine's own docs stay
honest.
