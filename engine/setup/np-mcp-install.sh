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

# Optional starter-overlay adoption ------------------------------------------------
# nervepack ships with no personal content. If no content overlay is configured yet,
# offer to clone the public `nervepack-content-example` pack as a ready-made starting
# overlay (generic skills, no personal data). Purely optional: declining, an empty
# stdin, or running non-interactively is a clean no-op — the engine never requires
# the generics. NP_STARTER_ADOPT_FORCE={adopt,decline} controls it non-interactively
# (used by tests/CI); NP_STARTER_ADOPT_SOURCE/NP_STARTER_ADOPT_PATH override the clone
# source/destination (used by tests, to avoid the network and $HOME/Code).
STARTER_REPO_URL="${NP_STARTER_ADOPT_SOURCE:-https://github.com/pat-browne/nervepack-content-example.git}"

offer_starter_adopt() {
  # Already have an overlay configured? Nothing to offer.
  [[ -f "$CFG/content-dir" ]] && return 0

  echo
  echo "Starter content: nervepack ships machinery-only, no personal skills."
  echo "The public 'nervepack-content-example' pack has generic skills you can adopt"
  echo "as a starting content overlay (freely editable/replaceable afterward)."

  local answer="${NP_STARTER_ADOPT_FORCE:-}"
  if [[ -z "$answer" ]]; then
    answer="$(ask 'Adopt the example content pack as your starter overlay? (adopt/decline)' 'decline')"
  fi

  if [[ "$answer" != "adopt" ]]; then
    echo "  - declined — no starter overlay adopted"
    return 0
  fi

  local default_dest="$HOME/Code/$(id -un 2>/dev/null || echo user)-content"
  local dest="${NP_STARTER_ADOPT_PATH:-}"
  [[ -z "$dest" ]] && dest="$(expand "$(ask 'Clone destination' "$default_dest")")"

  if [[ -e "$dest" ]]; then
    echo "  ! '$dest' already exists — skipping starter adoption" >&2
    return 0
  fi

  echo "Cloning $STARTER_REPO_URL -> $dest ..."
  mkdir -p "$(dirname "$dest")"
  if git clone -q "$STARTER_REPO_URL" "$dest" >/dev/null 2>&1; then
    printf '%s\n' "$dest" > "$CFG/content-dir"
    echo "  ✓ wrote $CFG/content-dir -> $dest"
    content="$dest"   # feed the rest of this run (MCP env, path-check roots)
  else
    echo "  ! clone failed — starter overlay not adopted" >&2
  fi
}

# --starter-only: exercise the step above in isolation (used by
# tests/onboard/test_starter_adopt.sh) without running the full guided install.
mkdir -p "$CFG"
if [[ "${1:-}" == "--starter-only" ]]; then
  offer_starter_adopt
  exit 0
fi

echo "── nervepack MCP install ──"
echo "Engine repo: $NP"

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
  offer_starter_adopt
fi

# 2. Team overlay (optional) -----------------------------------------------------
echo
echo "Team overlay (optional): a shared content layer above your personal one."
echo "Leave blank for none."
team="$(expand "$(ask 'Team content directory' '')")"
if [[ -n "$team" ]]; then
  if [[ -d "$team" ]]; then
    printf '%s\n' "$team" > "$CFG/team-dir"
    # The `team` feature is on by default (shared toggle) — configuring the dir is what
    # activates the overlay. We never flip the shared toggle here: that would commit to
    # the engine repo. If you've disabled it, re-enable with: nervepack-toggle team on.
    echo "  ✓ wrote $CFG/team-dir (the 'team' overlay is active by default)"
  else
    echo "  ! '$team' does not exist — skipping team overlay" >&2
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
