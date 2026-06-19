#!/usr/bin/env bash
# Register the SessionEnd performance-evaluator hook. Idempotent: re-running
# after a script path change REPLACES the stale entry (np-hook-lib.sh).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionEnd '~/Code/nervepack/engine/setup/np-evaluator.sh'
