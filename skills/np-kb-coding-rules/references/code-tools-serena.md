# Code tools — Serena details and re-enable steps

## Why native tools first

On small repos (static site, extensions), whole-file reads cost little and native
tools are faster than Serena — no MCP round-trip, no language-server cold-start,
no `activate_project` step. On Opus's large context window, native `Read`/`Grep`
rarely hits limits.

## Serena's symbolic tools

`find_symbol`, `find_referencing_symbols`, `replace_symbol_body`, `rename_symbol`,
`get_symbols_overview` — these genuinely win on a large codebase (symbol-granular
reads/edits + LSP-accurate renames beat regex). They do not pay off for small repos:
measured at 28 always-on tool schemas loaded + per-session dashboard, **zero actual
tool invocations** across 87 session boots (2026-06-08).

## Re-enabling Serena per-project

1. Set `enabledPlugins.serena = true` in the Claude plugin config.
2. Call `activate_project` for the target repo.
3. Call `initial_instructions` to load Serena's context.
4. Route nav/edits through Serena's symbolic tools so it earns the overhead.
5. Set `web_dashboard_open_on_launch: false` in `~/.serena/serena_config.yml`
   to suppress the auto-opened browser tab on each boot.

Plugin details (install path, `uvx` invocation): [[np-env-claude-plugin-stack]].
**Revisit agentic IDEs** (Serena, Cursor-style symbol servers, future options) when
repo scale or workflow makes the always-on overhead pay off.

## LSP tool

The built-in `LSP` tool provides go-to-definition, find-references, and diagnostics
straight from the language server — the default reach for "what calls this?" /
"where's this defined?" / "does this compile?" beyond what `Grep` answers. No
always-on MCP cost (invoked on demand).

For on-demand structural search-and-replace, use `ast-grep`/`sg` via Bash.
