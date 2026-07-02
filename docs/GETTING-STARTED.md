# Getting started with nervepack

nervepack is a context hub you run across your machines: skills, memory, tools, and
workflows your AI coding assistant reads every session. This walks you through a first
install on a new box. It leads with **Claude Code** (the proven host); for any other
agentic host, the same steps apply but the wiring is done by the onboarding contract in
[`../engine/onboard/ONBOARD.md`](../engine/onboard/ONBOARD.md).

> **Prerequisite:** an *agentic* host, one that can read/write files and run shell
> commands. A plain chat UI can only consume the knowledge as context, not self-wire.

## 1. Clone the engine

You need git first (the chicken-and-egg). Install just enough to clone:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/pat-browne/nervepack ~/Code/nervepack
```

## 2. Install the toolchain

```bash
~/Code/nervepack/engine/setup/00-apt-baseline.sh   # gh, jq, node, python, go, cron, build (sudo)
~/Code/nervepack/engine/setup/10-rustup.sh         # rustup, user-space, no sudo
~/Code/nervepack/engine/setup/20-claude-plugins.sh # Claude Code plugins (Claude host only)
```

**On macOS**, run `00-brew-baseline.sh` instead of `00-apt-baseline.sh` (the
Homebrew sibling — same toolset: gh, jq, node, go, and Python via uv). It runs on
the system `/bin/bash` (3.2), so no newer bash is required; `gh auth login` (step 5)
covers the GitHub credential the clone needs.

## 3. Onboard your host

Open your agent in `~/Code/nervepack` and run the onboarding walkthrough. Your agent
reads the tool-neutral contract, wires this host (skills, session hooks, scheduler),
writes `~/.config/nervepack/adapter.json`, and runs the doctor.

```text
/np-onboard      # or just say "onboard nervepack"
```

On a non-Claude host, follow [`../engine/onboard/ONBOARD.md`](../engine/onboard/ONBOARD.md)
directly. Either way, verify any time:

```bash
~/Code/nervepack/engine/setup/np-doctor.sh   # per-capability PASS/MISSING, non-zero on a real gap
```

## 4. Point the engine at your content

The engine is the shared machinery. Your skills, sources, memory, and metrics live in
a separate **content overlay** so they stay yours. Tell the engine where it is:

```bash
mkdir -p ~/.config/nervepack
echo "$HOME/Code/nervepack-content" > ~/.config/nervepack/content-dir
```

The `mkdir` is required the first time — `>` creates the *file* but not its parent
directory, so writing `content-dir` into a `~/.config/nervepack` that doesn't exist
yet fails with `no such file or directory`.

No overlay yet? Fork [`nervepack-content-example`](https://github.com/pat-browne/nervepack-content-example),
rename it to something private, and point at that. Skip this and the engine falls back
to its own root, which works, but gives you nowhere personal to grow.

**On a team?** You can point at a *second*, shared overlay that sits above your
personal one:

```bash
echo "$HOME/Code/team-nervepack-content" > ~/.config/nervepack/team-dir
```

The stack becomes `team > personal > engine`. Reads merge with the team winning
(a team skill or playbook shadows your personal one of the same name), and writes
still land in your personal overlay unless you explicitly "save to the team layer."
This is optional, and dormant until a team dir resolves.

## 5. Authenticate GitHub

```bash
gh auth login    # GitHub.com, HTTPS, login with a browser, authenticate Git
```

This sets up the credential helper so the maintenance jobs can `git push` your content
without prompting.

## 6. Schedule the maintenance agents

nervepack can keep itself tidy with scheduled agents (promote memory, compact skills,
lint). Some run as local crons, some as cloud routines on your AI account. Set up your
own from the payloads and cadence in [`../agents/README.md`](../agents/README.md). This
step is optional; nervepack works fine without it.

## 7. Verify and use it

Re-run the doctor. A green report means every MUST capability is wired.

```bash
~/Code/nervepack/engine/setup/np-doctor.sh
```

Then confirm the paths your docs and skills point at actually resolve on this machine.
The engine and content overlay live in separate repos, so a script named in one skill
sometimes moves under the other. This check catches a stale or renamed path before you
chase a dead command for a given feature:

```bash
python3 ~/Code/nervepack/engine/setup/np-path-check.py                        # engine only
# add your overlay to check its skills and docs too:
python3 ~/Code/nervepack/engine/setup/np-path-check.py ~/Code/nervepack ~/Code/nervepack-content
```

A clean run prints `all setup/onboard path references resolve ✓`. Any hit names the
file, the line, and the path to fix. The same check runs in CI, so the engine's own docs
stay honest.

From here, every session loads `skills/*`, a SessionStart directive tells the session to
consult nervepack first, and `/np-core-sync` / `/np-core-contribute` are available as
slash commands.

## What about the MCP server?

The MCP server is a *surface*, not a bootstrapper. It can't install nervepack from
nothing, because the server itself lives in the engine repo you just cloned. What it
does is expose nervepack's tools, resources, and prompts to any MCP-speaking client.

- **On Claude Code** you don't need to do anything extra. A full onboard installs the
  `5x` hooks, and one of them (`58-install-mcp.sh`) registers the MCP server for you
  when the `mcp` toggle is on. Your skills, the session directive, and lifecycle
  capture come from the onboard itself, not from MCP.
- **On any other MCP client** (Cursor, Codex, a local-model client) point it at the
  server instead of wiring each script by hand.

Either way, the shortcut is one guided command:

```bash
~/Code/nervepack/engine/bin/nervepack-install
```

It configures your content (and optional team) overlay, registers the server, and runs
the doctor. It re-runs safely and takes defaults on a non-interactive shell. See
[`../engine/onboard/MCP.md`](../engine/onboard/MCP.md) for the full tool and resource
list and the write-gating story.
