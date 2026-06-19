# Use nervepack from any MCP client

nervepack ships an MCP server so any MCP-speaking host (Cursor, Codex, a local
model's MCP client, …) gets the same skills, memory, and tools that Claude Code does
— without wiring each script by hand. This is the distribution reference; for the
broader self-wiring contract see [`ONBOARD.md`](ONBOARD.md), and for the conceptual
overview see [`../../docs/FEATURES.md`](../../docs/FEATURES.md) (Part 4).

## What it is

A pure-stdlib **stdio** server (`engine/setup/np-mcp-server.py`, launched by
`engine/bin/nervepack-mcp`). No daemon, no network port: your client spawns it per
session over stdin/stdout and it exits with the session. It reads your content
overlay through `NP_CONTENT_DIR`, exactly like the rest of nervepack.

## Install — the generic `mcpServers` block

Add this to your client's MCP config. Use an **absolute path** to the launcher:

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

`NP_CONTENT_DIR` is optional — omit it to fall back to the engine root (the legacy
single-repo layout). Set it to your overlay to serve your personal skills/memory.

### Per-client notes

- **Claude Code** — don't hand-edit. `engine/setup/58-install-mcp.sh` already
  registers the server (`claude mcp add nervepack -s user -- …/engine/bin/nervepack-mcp`)
  when the `mcp` toggle is on. Re-run that script after moving the repo.
- **Cursor** — put the block above in `~/.cursor/mcp.json` (or the project
  `.cursor/mcp.json`).
- **Any other MCP client** — drop the same block into whatever file your client reads
  its MCP server list from.

## What it exposes

**Tools** (`tools/list`):

| Tool | Does | Gate |
|---|---|---|
| `nervepack_doctor` | Verify this install against the onboard contract | — (read) |
| `nervepack_recall` | Recall topic-matched episodic notes / playbooks / strategies | — (read) |
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
`nervepack://{skills,sources,wiki,playbooks,strategies,episodic,dashboard}/<name>` resolved from
your overlay.

**Prompts** (`prompts/list` / `prompts/get`): `nervepack-directive` — the
"consult nervepack first" session directive, for hosts that inject a prompt at session
start.

## Write-gating & safety

The server is **safe-by-default**:

- **Reads** (`doctor`, `recall`, `dashboard`, resources, prompts) are always available.
- **Writes** are gated by the `mcp.writes` param (**default on**). Turn them off with
  `nervepack-toggle param mcp.writes off` to make the server strictly read-only.
- **Durable git commits** (`nervepack_contribute`, and the `suggestions` implement
  action) are gated separately by `mcp.contribute` (**default off**) — durable
  auto-commit is opt-in because it bypasses the human-reviewed contribute gate.
- It is **stdio-only** — no listening socket. Commits stay auditable: authored as you,
  explicit-path staging, never force-push.

## See also

- [`ONBOARD.md`](ONBOARD.md) — the full onboarding contract; MCP is one way to satisfy it.
- [`capabilities.json`](capabilities.json) — the machine-readable capability list.
- [`../../docs/FEATURES.md`](../../docs/FEATURES.md) — Part 4, the MCP layer's purpose and worked example.
