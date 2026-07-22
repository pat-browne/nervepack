#!/usr/bin/env bash
# Baseline Ubuntu dev packages required by Claude Code plugins, language
# servers, and the nervepack repo's own setup scripts. Idempotent: safe to re-run.
set -euo pipefail

if ! command -v sudo >/dev/null; then
  echo "sudo is required" >&2; exit 1
fi

sudo apt update
sudo apt install -y \
  git \
  gh \
  jq \
  nodejs npm \
  python3-pip python3-venv pipx \
  golang-go \
  build-essential \
  curl ca-certificates cron

# Why each addition beyond the obvious:
#   gh   — GitHub auth flow for first-time clone/push from a fresh machine
#   jq   — required by 50-install-session-hook.sh (atomic settings.json edit)
#   cron — required by cli.py setup install-memory-cron; usually present but force it

echo
echo "Installed versions:"
git --version
gh --version | head -1
jq --version
node --version
npm --version
python3 --version
go version || true
