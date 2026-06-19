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

failed=()
for p in "${PLUGINS[@]}"; do
  echo "==> $p"
  if ! claude plugin install "${p}@claude-plugins-official"; then
    failed+=("$p")
  fi
done

# Karpathy's coding guidelines are absorbed natively into the np-kb-coding-rules
# skill (credited in NOTICE) — no external plugin install needed.

echo
if ((${#failed[@]})); then
  echo "Failed: ${failed[*]}" >&2
  exit 1
fi
echo "All plugins installed."
