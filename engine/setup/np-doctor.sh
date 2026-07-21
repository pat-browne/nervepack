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
      local out rc
      out="$(printf 'ping' | python3 "$HERE/np_model.py" complete 2>/dev/null)"
      rc=$?
      [[ $rc -eq 0 && -n "$out" ]] && echo PASS || echo FAIL ;;
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
    team)
      tlist="$(source "$HERE/np-content-lib.sh" 2>/dev/null; np_team_dirs 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
      torigin="$(source "$HERE/np-content-lib.sh" 2>/dev/null; np_team_dir_origin 2>/dev/null)"
      tcount="$(source "$HERE/np-content-lib.sh" 2>/dev/null; np_team_dirs 2>/dev/null | grep -c .)"
      if [[ -z "$tlist" ]]; then
        if [[ "$torigin" != none ]]; then
          echo "WARN (team layer configured (origin $torigin) but invalid — over-cap (>4) or a missing dir; falling back to personal-only)"
        else
          echo "PASS (no team layer configured)"
        fi
      elif np_enabled team; then
        tmode="$(source "$HERE/np-layer-lib.sh" 2>/dev/null; np_merge_mode 2>/dev/null || echo override)"
        echo "PASS (team layers ($tcount): $tlist — origin $torigin, merge $tmode)"
      else
        echo "PASS (team layers ($tcount): $tlist but the 'team' toggle is OFF — not merged)"
      fi
      ;;
    dashboard-data)
      # In a split layout, dashboard/data must be a symlink resolving to an existing
      # directory (the bridge created by 35-link-dashboard-data.sh). In a single-repo
      # layout the real dir is already there — check it directly.
      local cdir ddlink ddresolved
      cdir="$(source "$HERE/np-content-lib.sh" 2>/dev/null; np_content_dir 2>/dev/null)"
      ddlink="$NP/dashboard/data"
      if [[ -z "$cdir" ]]; then
        echo "WARN (content dir unresolvable — cannot verify dashboard data bridge)"
      elif [[ "$cdir" == "$NP" ]]; then
        # Single-repo: real dir should exist.
        [[ -d "$ddlink" ]] && echo PASS || echo "WARN (dashboard/data dir missing — run 35-link-dashboard-data.sh)"
      else
        # Split layout: must be a symlink pointing at the content overlay.
        if [[ -L "$ddlink" ]]; then
          ddresolved="$(cd -P "$ddlink" 2>/dev/null && pwd)"
          if [[ -d "$ddresolved" ]]; then
            echo PASS
          else
            echo "WARN (dashboard/data symlink exists but target does not resolve — run 35-link-dashboard-data.sh)"
          fi
        elif [[ -d "$ddlink" ]]; then
          echo "WARN (dashboard/data is a real directory, not a symlink into the content overlay — metrics may load from the wrong location)"
        else
          echo "WARN (dashboard/data bridge missing — run 35-link-dashboard-data.sh to create the symlink into the content overlay; the dashboard will show no metrics until then)"
        fi
      fi ;;
    hook-scripts)
      local settings="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
      if [[ ! -f "$settings" ]]; then
        echo "PASS (no settings.json at $settings)"
        return
      fi
      command -v jq >/dev/null || { echo "SKIP (jq unavailable)"; return; }
      local broken=() cmd script
      while IFS= read -r cmd; do
        [[ -z "$cmd" ]] && continue
        cmd="${cmd%$'\r'}"       # jq on Windows emits \r\n; read -r strips \n but not \r
        cmd="${cmd/#\~/$HOME}"   # expand ~/
        script="${cmd%% *}"     # first token — strip trailing args / &
        [[ "$script" != */* ]] && continue   # skip bare command names
        [[ -e "$script" ]] || broken+=("$script")
      done < <(jq -r '(.hooks // {}) | .. | objects | select(.type? == "command") | .command' "$settings" 2>/dev/null)
      if [[ ${#broken[@]} -eq 0 ]]; then
        echo PASS
      else
        printf 'FAIL (%d missing script(s): %s)\n' "${#broken[@]}" "${broken[*]}"
      fi ;;
    resume-pointer)
      local writer="$NP/engine/nervepack_engine/hooks/resume_write.py"
      if [[ ! -f "$writer" ]]; then
        echo "WARN (resume_write.py missing — run engine/setup/61-install-resume-hook.sh)"
        return
      fi
      local settings="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
      if [[ ! -f "$settings" ]]; then
        echo "WARN (no settings.json at $settings — run engine/setup/61-install-resume-hook.sh)"
        return
      fi
      command -v jq >/dev/null || { echo "SKIP (jq unavailable)"; return; }
      local cmds
      cmds="$(jq -r '(.hooks // {}) | .. | objects | select(.type? == "command") | .command' "$settings" 2>/dev/null)"
      if grep -qE 'np-resume-sessionstart\.sh|cli\.py hook resume-sessionstart' <<<"$cmds" \
        && grep -qE 'np-resume-recall\.sh|cli\.py hook resume-recall' <<<"$cmds"; then
        echo PASS
      else
        echo "WARN (resume-pointer hooks not registered in $settings — run engine/setup/61-install-resume-hook.sh)"
      fi ;;
    scheduled-auth-token)
      source "$HERE/np-token-lib.sh" 2>/dev/null || { echo SKIP; return; }
      local st word
      st="$(np_claude_token_status)"
      word="${st%% *}"
      case "$word" in
        ok)   echo "PASS ($st)" ;;
        warn) echo "WARN (rotation window — run engine/setup/62-install-scheduled-auth-token.sh --rotate; $st)" ;;
        *)    echo "WARN (no scheduled-auth token — run engine/setup/62-install-scheduled-auth-token.sh; scheduled memory-promote/refine/compact crons fail 'Not logged in' without it)" ;;
      esac ;;
    pii_filter_full)
      python3 -c "import presidio_analyzer" >/dev/null 2>&1 \
        && echo PASS \
        || echo "FAIL (run: python3 engine/nervepack_engine/cli.py setup install-pii-deps)" ;;
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
    # Run the host-authored verify with pipefail DISABLED. These are boolean
    # "is it wired" checks, and the idiomatic form is `producer | grep -q PAT`
    # (e.g. `launchctl list | grep -q com.nervepack`, `crontab -l | grep -q …`).
    # `grep -q` exits on first match and closes the pipe, so the producer takes
    # SIGPIPE (141); under the script's `pipefail` that 141 would propagate and
    # report a genuinely-wired capability as FAIL. Default pipe semantics (last
    # command's status) are exactly what a boolean check wants.
    wired)
      if [[ -n "$verify" ]] && ( set +o pipefail; eval "$verify" ) >/dev/null 2>&1; then
        echo PASS; else echo FAIL; fi ;;
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
