#!/usr/bin/env bash
# Install the curated Claude Code plugin set. Idempotent: `claude plugin install`
# is a no-op when the plugin is already present.
set -euo pipefail

if ! command -v claude >/dev/null; then
  echo "claude CLI not found on PATH" >&2; exit 1
fi
if ! command -v git >/dev/null; then
  echo "git is required (plugin install uses git clone). Run 00-apt-baseline.sh first." >&2
  exit 1
fi

PLUGINS=(
  # workflow
  superpowers
  code-review
  commit-commands
  security-guidance
  frontend-design
  # language servers
  typescript-lsp
  pyright-lsp
  gopls-lsp
  rust-analyzer-lsp
  # external integrations
  github
  context7
  playwright
  serena
  stripe
)

# Plugins installed but left OFF by default (opt in per-project via that
# project's .claude/settings.local.json). Global-enable means every Claude
# Code process — including every subagent/one-shot spawned via Agent/Task/
# Workflow — launches its own independent MCP server instance; with Serena's
# uvx-from-git launch cost and subagent fan-out, that produces a burst of
# short-lived server spawns that looks like a launch loop. Install still
# happens so it's available and pre-warmed; just not globally active.
DEFAULT_OFF=(
  serena
)

failed=()
for p in "${PLUGINS[@]}"; do
  echo "==> $p"
  if ! claude plugin install "${p}@claude-plugins-official"; then
    failed+=("$p")
  fi
done

for p in "${DEFAULT_OFF[@]}"; do
  echo "==> disabling $p globally (opt in per-project instead)"
  claude plugin disable "${p}@claude-plugins-official" || true
done

# Karpathy's coding guidelines are absorbed natively into the np-kb-coding-rules
# skill (credited in NOTICE) — no external plugin install needed.

echo
if ((${#failed[@]})); then
  echo "Failed: ${failed[*]}" >&2
  exit 1
fi
echo "All plugins installed."
