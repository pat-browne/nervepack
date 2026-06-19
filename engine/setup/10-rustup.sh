#!/usr/bin/env bash
# Install rustup if it isn't already on PATH. Prefer this over apt's rustc.
set -euo pipefail

if command -v rustup >/dev/null; then
  echo "rustup already installed: $(rustup --version)"
  exit 0
fi

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# shellcheck disable=SC1091
. "$HOME/.cargo/env"

rustc --version
cargo --version
