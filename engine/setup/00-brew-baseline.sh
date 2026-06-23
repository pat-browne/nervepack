#!/usr/bin/env bash
# Baseline macOS dev tools required by Claude Code plugins, language servers, and
# the nervepack repo's own setup scripts. The Homebrew sibling of 00-apt-baseline.sh
# (the Ubuntu/apt path) — same logical toolset, mac-native delivery. Idempotent:
# `brew install` no-ops a formula that's already present, so it's safe to re-run.
#
# Runs on the stock macOS /bin/bash (3.2): no bash 4+ constructs here (see
# tests/meta/test_macos_portability.sh).
set -euo pipefail

if ! command -v brew >/dev/null; then
  echo "Homebrew is required. Install it from https://brew.sh then re-run." >&2
  exit 1
fi

# git + a C toolchain ship with the Xcode Command Line Tools on macOS (the
# build-essential analogue); curl/ca-certificates are in the base system, and
# launchd replaces cron (70-install-memory-launchd.sh). So brew only owns the rest.
command -v git >/dev/null 2>&1 || xcode-select --install || true

# Python is NOT brewed: the workspace convention is uv for everything Python
# (never pip), and uv manages its own interpreters — so uv owns Python here.
brew install gh jq node go uv

# Install a uv-managed Python interpreter (latest stable uv knows about).
uv python install

echo
echo "Installed versions:"
git --version
gh --version | head -1
jq --version
node --version
npm --version
go version || true
uv --version
uv python list --only-installed 2>/dev/null | head -1 || true
