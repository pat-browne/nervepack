# Use nervepack from any MCP client

nervepack ships an MCP server so any MCP-speaking host (Cursor, Codex, a local
model's MCP client, …) gets the same skills, memory, and tools that Claude Code does,
without wiring each script by hand. This is the distribution reference. For the
broader self-wiring contract see [`ONBOARD.md`](ONBOARD.md); for the conceptual
overview see [`../../docs/FEATURES.md`](../../docs/FEATURES.md) (Part 4).

## What it is

A pure-stdlib **stdio** server (`engine/setup/np-mcp-server.py`, launched by
`engine/bin/nervepack-mcp`). No daemon, no network port: your client spawns it per
session over stdin/stdout and it exits with the session. It reads your content
overlay through `NP_CONTENT_DIR`, exactly like the rest of nervepack.

## Install: one guided command (recommended)

From a cloned repo, run the guided installer:

```bash
~/Code/nervepack/engine/bin/nervepack-install
```

It walks you through it: enter your **content directory** (where your personal
skills/memory live — blank uses the engine root), optionally a **team content
directory**, then it registers the MCP server with your host (Claude Code via
`58-install-mcp.sh`; any other client gets the `mcpServers` block printed for you),
and finally verifies the wiring with **`np-doctor.sh`** plus a check that the paths
your docs and skills reference actually resolve (`np-path-check.py`). Re-runnable and
idempotent; on a non-interactive shell (CI) every prompt takes its default and it
never blocks.

## Install: the generic `mcpServers` block (manual)

Prefer to wire it by hand? Add this to your client's MCP config. Use an **absolute
path** to the launcher:

```json
{
  "mcpServers": {
    "nervepack": {
      "command": "/home/<you>/Code/nervepack/engine/bin/nervepack-mcp",
      "env": {
        "NP_CONTENT_DIR": "/home/<you>/Code/nervepack-content"
      }
    }
  }
}
```

`NP_CONTENT_DIR` is optional. Omit it to fall back to the engine root (the legacy
single-repo layout). Set it to your overlay to serve your personal skills/memory.

## Windows without Git for Windows

The server is native Python and **no longer needs Git-bash** for its read tools or
for `toggle`/`sync`/`capture`/`evaluate` — those run in-process (verified by a
`windows-latest` CI lane with Git-bash stripped from `PATH`). On a Windows host with
**no Git for Windows**, point the `command` at the bash-free `.cmd` launcher instead:

```json
{
  "mcpServers": {
    "nervepack": {
      "command": "C:\\Users\\<you>\\Code\\nervepack\\engine\\bin\\nervepack-mcp.cmd",
      "env": { "NP_CONTENT_DIR": "C:\\Users\\<you>\\Code\\nervepack-content" }
    }
  }
}
```

It spawns the server with native `python` (which must be on `PATH`) — no bash
anywhere. The two maintenance tools that still shell out to the agent-mode crons
(`nervepack_flush`, `nervepack_maintain`) **refuse cleanly** on a bash-free host
("needs bash — not supported bash-free yet"); everything else works. If Git for
Windows *is* installed, use the POSIX `nervepack-mcp` launcher (it also pins
`NP_BASH` so those two tools can shell out).

### Per-client notes

- **Claude Code**: don't hand-edit. `engine/setup/58-install-mcp.sh` already
  registers the server (`claude mcp add nervepack -s user -- …/engine/bin/nervepack-mcp`)
  when the `mcp` toggle is on. Re-run that script after moving the repo.
- **Cursor**: put the block above in `~/.cursor/mcp.json` (or the project
  `.cursor/mcp.json`).
- **Any other MCP client**: drop the same block into whatever file your client reads
  its MCP server list from.

## What it exposes

**Tools** (`tools/list`):

| Tool | Does | Gate |
|---|---|---|
| `nervepack_doctor` | Verify this install against the onboard contract | — (read) |
| `nervepack_recall` | Recall topic-matched episodic notes / lessons | — (read) |
| `nervepack_dashboard` | Read dashboard data (`summary` counts or raw `metrics`) | — (read) |
| `nervepack_toggle` | Get/list/set feature toggles | `mcp.writes` |
| `nervepack_sync` | Fast-forward sync the repo with origin | `mcp.writes` |
| `nervepack_capture` | Capture a session to the episodic inbox | `mcp.writes` |
| `nervepack_evaluate` | Score a session into the evaluator inbox | `mcp.writes` |
| `nervepack_flush` | Promote the local inboxes into the committed layers | `mcp.writes` |
| `nervepack_suggestions` | list/review/resolve/clear/implement/reject dashboard suggestions | `mcp.writes` (implement also `mcp.contribute`) |
| `nervepack_maintain` | Run a maintenance job (promote/maintain/aggregate/skills) | `mcp.writes` |
| `nervepack_contribute` | Write a durable skill/source/wiki page and git-commit it | `mcp.contribute` |

**Resources** (`resources/list` / `resources/read`): `nervepack://index` (the skill
index), `nervepack://dashboard/metrics` (the metrics time series), and every file under
`nervepack://{skills,wiki,memory/episodic,memory/lessons,dashboard}/<name>`
resolved from your overlay. Sources aren't a separate prefix, they live inside the wiki
(`nervepack://wiki/topics/<topic>/<name>`), and concepts under
`nervepack://wiki/concepts/<concept>/<name>`.

**Prompts** (`prompts/list` / `prompts/get`): `nervepack-directive`, the
"consult nervepack first" session directive for hosts that inject a prompt at session
start.

## Write-gating & safety

The server is **safe-by-default**:

- **Reads** (`doctor`, `recall`, `dashboard`, resources, prompts) are always available.
- **Writes** are gated by the `mcp.writes` param (**default on**). Turn them off with
  `nervepack-toggle param mcp.writes off` to make the server strictly read-only.
- **Durable git commits** (`nervepack_contribute`, and the `suggestions` implement
  action) are gated separately by `mcp.contribute` (**default off**). Durable
  auto-commit is opt-in because it bypasses the human-reviewed contribute gate.
- It is **stdio-only** (no listening socket). Commits stay auditable: authored as you,
  explicit-path staging, never force-push.

## See also

- [`ONBOARD.md`](ONBOARD.md): the full onboarding contract. MCP is one way to satisfy it.
- [`capabilities.json`](capabilities.json): the machine-readable capability list.
- [`../../docs/FEATURES.md`](../../docs/FEATURES.md): Part 4, the MCP layer's purpose and worked example.
