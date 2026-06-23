#!/usr/bin/env bash
# SessionStart: refresh performance metrics, then open the dashboard — ONCE per
# OS boot, never more.
#
# Why once-per-boot (this is load-bearing, do not "simplify" to per-session):
#   SessionStart fires on EVERY session start and also on resume/clear/compact
#   (a "" matcher matches all sources). Under a remote-desktop session
#   (gnome-remote-desktop / RDP), opening a GUI browser here perturbs the desktop
#   enough to trigger remote-control's auto-reconnect, which spawns a NEW Claude
#   session, which re-fires this hook, which opens the browser again — a
#   focus-steal/reconnect feedback loop that span up ~150 sessions in seconds,
#   one xdg-open each (158 transcripts in ~/.claude/projects, ~1.5s apart).
#   Guarding the OPEN to once per boot severs the loop: the 2nd firing returns
#   before opening anything, so nothing re-opens and the cycle can't sustain.
#   Matching only `startup` does NOT help — each loop iteration is a fresh
#   startup; the boot marker is what breaks it.
#
# Gated by the evaluator.dashboard_open param (default on — declared in toggles.conf
#   so it is discoverable; flip off per-machine with
#   `nervepack-toggle evaluator.dashboard_open off`). Fail-open throughout: this
# must never block or break session startup.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"   # engine/setup -> repo root
source "$HERE/np-toggle-lib.sh"

[[ "$(np_param evaluator.dashboard_open on)" == "on" ]] || exit 0

# Once-per-boot guard. boot_id changes only on reboot, so the marker matches for
# the life of this boot and every later session start short-circuits here.
boot_id="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown)"
marker="${NP_DASH_MARKER:-$HOME/.cache/nervepack/dashboard-open-boot}"
[[ "$(cat "$marker" 2>/dev/null)" == "$boot_id" ]] && exit 0
mkdir -p "$(dirname "$marker")" 2>/dev/null || true
printf '%s' "$boot_id" > "$marker" 2>/dev/null || true

# 1. Refresh (drain inbox -> metrics.jsonl -> metrics.js -> commit/push; no-op
#    when the inbox is empty). Best-effort. NP_DASH_AGGREGATE lets tests substitute
#    a no-op for the real (repo-mutating) aggregate step.
"${NP_DASH_AGGREGATE:-$HERE/73-aggregate-metrics.sh}" >/dev/null 2>&1 || true

# 2. Open the nervepack metrics dashboard. NP_DASH_OPENER lets tests substitute
#    a non-GUI opener; default xdg-open on Linux, open on macOS (np_resolve_opener).
#    (Serena opens its own dashboard once per
#    MCP-server start — we don't touch that.) URL is file:// by default, or
#    http://127.0.0.1:<port>/ when evaluator.dashboard_serve is on (the helper
#    starts the local backend if it isn't already running).
# shellcheck source=/dev/null
source "$HERE/np-dashboard-launch.sh"
url="$(np_dashboard_url)"
opener="$(np_resolve_opener || true)"
command -v "$opener" >/dev/null 2>&1 || exit 0
"$opener" "$url" >/dev/null 2>&1 || true
