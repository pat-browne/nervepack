#!/usr/bin/env bash
# nervepack doctor — verify an install against the onboard contract
# (onboard/capabilities.json). The linchpin that makes agent-generated wiring
# trustworthy: generate → doctor → fix. Deterministic.
#
#  - check:core    capabilities are verified by the shipped, host-neutral checks below.
#  - check:adapter capabilities are verified by running the `verify` command the
#                  onboarding agent recorded in adapter.json (the host knows how to
#                  prove its own wiring; the doctor just runs it).
#
# Reports each capability per tier (PASS / FAIL / MISSING / UNSUPPORTED). Exits
# non-zero on any MUST that is not PASS; SHOULD shortfalls warn only.
#
# Config (env, for tests + alt installs): NP_DIR · NP_CAPABILITIES · NP_ADAPTER ·
# CLAUDE_BIN / NP_LLM_BACKEND (for the llm-cli smoke).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="${NP_DIR:-$(cd "$HERE/../.." && pwd)}"
CAPS="${NP_CAPABILITIES:-$NP/engine/onboard/capabilities.json}"
ADAPTER="${NP_ADAPTER:-$HOME/.config/nervepack/adapter.json}"
source "$HERE/np-toggle-lib.sh" 2>/dev/null || true

command -v jq >/dev/null || { echo "doctor: jq required" >&2; exit 2; }
[[ -f "$CAPS" ]] || { echo "doctor: capabilities.json not found at $CAPS" >&2; exit 2; }

# --- core (host-neutral) checks, by capability id ---
core_check() {
  case "$1" in
    llm-cli)
      local out; out="$(printf 'ping' | "$HERE/np-llm.sh" complete 2>/dev/null)"
      [[ -n "$out" ]] && echo PASS || echo FAIL ;;
    git-sync)
      git -C "$NP" rev-parse --git-dir >/dev/null 2>&1 \
        && git -C "$NP" remote get-url origin >/dev/null 2>&1 && echo PASS || echo FAIL ;;
    toggles)
      declare -F np_enabled >/dev/null 2>&1 && echo PASS || echo FAIL ;;
    content)
      local cdir origin
      cdir="$(source "$HERE/np-content-lib.sh" 2>/dev/null; np_content_dir 2>/dev/null)"
      origin="$(source "$HERE/np-content-lib.sh" 2>/dev/null; np_content_dir_origin 2>/dev/null)"
      if [[ -z "$cdir" || ! -d "$cdir" ]]; then
        echo FAIL
      elif [[ "$origin" == default ]]; then
        # Dir exists so this is a PASS (fail-open), but warn: personal-content writers
        # SKIP their commit on this implicit engine-root fallback (issue #12). Set
        # NP_CONTENT_DIR or write ~/.config/nervepack/content-dir to opt in explicitly.
        echo "PASS (implicit engine-root fallback — set NP_CONTENT_DIR or ~/.config/nervepack/content-dir; writers skip commits until then)"
      else
        echo PASS
      fi ;;
    *) echo SKIP ;;
  esac
}

# --- adapter (host-specific) checks: run the verify the agent recorded ---
adapter_check() {
  [[ -f "$ADAPTER" ]] || { echo MISSING; return; }
  local status verify
  status="$(jq -r --arg id "$1" '.capabilities[$id].status // "missing"' "$ADAPTER" 2>/dev/null)"
  verify="$(jq -r --arg id "$1" '.capabilities[$id].verify // ""'        "$ADAPTER" 2>/dev/null)"
  case "$status" in
    unsupported) echo UNSUPPORTED ;;
    wired) if [[ -n "$verify" ]] && eval "$verify" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi ;;
    *) echo MISSING ;;
  esac
}

echo "nervepack doctor — contract: $CAPS"
[[ -f "$ADAPTER" ]] && echo "adapter: $ADAPTER" || echo "adapter: (none at $ADAPTER)"
echo

must_fail=0
n="$(jq '.capabilities | length' "$CAPS")"
for i in $(seq 0 $((n-1))); do
  id="$(jq -r ".capabilities[$i].id"    "$CAPS")"
  tier="$(jq -r ".capabilities[$i].tier" "$CAPS")"
  check="$(jq -r ".capabilities[$i].check" "$CAPS")"
  if [[ "$check" == core ]]; then st="$(core_check "$id")"; else st="$(adapter_check "$id")"; fi
  printf '  [%-6s] %-22s %s\n' "$tier" "$id" "$st"
  # A status may carry an advisory suffix after PASS (e.g. the content check's
  # implicit-fallback warning) — treat any "PASS…" prefix as a pass.
  [[ "$tier" == MUST && "$st" != PASS* ]] && must_fail=1
done

echo
if [[ $must_fail -eq 0 ]]; then
  echo "doctor: MUST tier OK ✓  (SHOULD shortfalls above are advisory)"
  exit 0
else
  echo "doctor: MUST tier FAILED ✗  — fix the items above and re-run"
  exit 1
fi
