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
echo "$HOME/Code/nervepack-content" > ~/.config/nervepack/content-dir
```

No overlay yet? Fork [`nervepack-content-example`](https://github.com/pat-browne/nervepack-content-example),
rename it to something private, and point at that. Skip this and the engine falls back
to its own root, which works, but gives you nowhere personal to grow.

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

From here, every session loads `skills/*`, a SessionStart directive tells the session to
consult nervepack first, and `/np-core-sync` / `/np-core-contribute` are available as
slash commands.

## Prefer to connect over MCP?

If your host speaks MCP (Cursor, Codex, a local-model client), you can skip per-script
wiring and point your MCP client at the nervepack server instead. See
[`../engine/onboard/MCP.md`](../engine/onboard/MCP.md).
