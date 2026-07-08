#!/usr/bin/env bash
# Guided nervepack MCP install — one command, end to end:
#   1. configure the content overlay        (~/.config/nervepack/content-dir)
#   2. optionally configure a team overlay   (~/.config/nervepack/team-dir + `team` toggle)
#   3. register the MCP server with your host (Claude Code via 58-install-mcp.sh;
#      otherwise print the generic mcpServers block for your client)
#   4. verify the install (doctor + a check that documented feature paths resolve)
#
# Interactive, but falls back to safe defaults when stdin has no input (CI/headless),
# so it never blocks: a closed/empty stdin == "accept the default" for every prompt.
# Idempotent and re-runnable. Reads answers line-by-line from stdin.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
# np-content-lib resolves config from $HOME/.config/nervepack (not XDG) — match it.
CFG="$HOME/.config/nervepack"

# ask <prompt> <default>: read one line from stdin; EOF/blank -> default. The prompt
# goes to stderr so it shows even when stdout is captured, and never to the answer.
ask() {
  local ans=""
  printf '%s [%s]: ' "$1" "${2:-blank}" >&2
  read -r ans || true
  printf '%s' "${ans:-$2}"
}
expand() { printf '%s' "${1/#\~/$HOME}"; }   # expand a leading ~

echo "── nervepack MCP install ──"
echo "Engine repo: $NP"
mkdir -p "$CFG"

# 1. Content overlay -------------------------------------------------------------
echo
echo "Content overlay: where your personal skills / memory / wiki live."
echo "Leave blank to use the engine root (single-repo layout)."
content="$(expand "$(ask 'Content directory' '')")"
if [[ -n "$content" ]]; then
  if [[ -d "$content" ]]; then
    printf '%s\n' "$content" > "$CFG/content-dir"
    echo "  ✓ wrote $CFG/content-dir -> $content"
  else
    echo "  ! '$content' does not exist — skipping (engine root will be used)" >&2
    content=""
  fi
else
  rm -f "$CFG/content-dir" 2>/dev/null || true
  echo "  ✓ using the engine root (no content overlay configured)"
fi

# 2. Team overlay (optional) -----------------------------------------------------
echo
echo "Team overlay (optional): a shared content layer above your personal one."
echo "Leave blank for none. Multiple team dirs may be given comma-separated, highest"
echo "precedence first (max 4) — e.g. squad-dir,division-dir."
team_raw="$(ask 'Team content directory' '')"
if [[ -n "$team_raw" ]]; then
  # Split on ',', trim each entry, expand a leading ~ per-entry (expand() only
  # handles one leading ~ on the whole string, so it must run per split piece —
  # see np_team_dirs in np-content-lib.sh, which this mirrors).
  team_entries=() team_err=""
  IFS=',' read -ra _team_parts <<< "$team_raw"
  for p in "${_team_parts[@]}"; do
    d="${p#"${p%%[![:space:]]*}"}"   # ltrim
    d="${d%"${d##*[![:space:]]}"}"   # rtrim
    [[ -n "$d" ]] || continue
    team_entries+=("$(expand "$d")")
  done
  if [[ ${#team_entries[@]} -eq 0 ]]; then
    team_err="no team dir given"
  elif [[ ${#team_entries[@]} -gt 4 ]]; then
    team_err=">4 team dirs — max 4"
  else
    for d in "${team_entries[@]}"; do
      if [[ ! -d "$d" ]]; then
        team_err="'$d' does not exist"
        break
      fi
    done
  fi
  if [[ -z "$team_err" ]]; then
    team="$(IFS=,; printf '%s' "${team_entries[*]}")"
    printf '%s\n' "$team" > "$CFG/team-dir"
    # The `team` feature is on by default (shared toggle) — configuring the dir is what
    # activates the overlay. We never flip the shared toggle here: that would commit to
    # the engine repo. If you've disabled it, re-enable with: nervepack-toggle team on.
    echo "  ✓ wrote $CFG/team-dir (the 'team' overlay is active by default)"
  else
    echo "  ! $team_err — skipping team overlay" >&2
  fi
fi

# 3. Register the MCP server with the host ---------------------------------------
echo
if command -v claude >/dev/null 2>&1; then
  echo "Registering the MCP server with Claude Code (user scope)…"
  bash "$HERE/58-install-mcp.sh"
else
  echo "Claude CLI not found — add this to your MCP client's config (absolute path):"
  printf '  {\n    "mcpServers": {\n      "nervepack": {\n        "command": "%s/engine/bin/nervepack-mcp"' "$NP"
  [[ -n "$content" ]] && printf ',\n        "env": { "NP_CONTENT_DIR": "%s" }' "$content"
  printf '\n      }\n    }\n  }\n'
fi

# 4. Verify ----------------------------------------------------------------------
echo
echo "Running the doctor to verify the install…"
echo
bash "$HERE/np-doctor.sh" || true

# Confirm the paths the docs + skills point at actually resolve on this machine —
# across the engine and whatever overlay(s) we just configured. Advisory (fail-open):
# a stale reference is worth surfacing but must never block the install.
echo
echo "Checking that documented feature paths resolve…"
if command -v python3 >/dev/null 2>&1; then
  pc_roots=("$NP")
  [[ -n "${content:-}" && -d "$content" ]] && pc_roots+=("$content")
  [[ -n "${team:-}"    && -d "$team"    ]] && pc_roots+=("$team")
  python3 "$HERE/np-path-check.py" "${pc_roots[@]}" || true
else
  echo "  (skipped — python3 not found)"
fi

echo
echo "Done. Re-run any time:  bash $HERE/np-mcp-install.sh"
