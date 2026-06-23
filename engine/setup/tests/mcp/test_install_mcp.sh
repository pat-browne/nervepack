#!/usr/bin/env bash
# np-test: 58-install-mcp | happy
# 58-install-mcp.sh registers the nervepack MCP server with the `claude` CLI at user
# scope: `claude mcp add nervepack -s user -- <repo>/engine/bin/nervepack-mcp`,
# remove-then-add for idempotency.
# We stand up a stub `claude` that maintains a tiny registry file so we can assert
# REAL state: after the run the registry holds exactly one `nervepack` entry whose
# command is the launcher path; after a SECOND run it still holds exactly one
# (remove-then-add does not duplicate).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../58-install-mcp.sh"
REPO="$(cd "$HERE/../../../.." && pwd)"   # tests/mcp -> setup -> engine -> repo
LAUNCHER="$REPO/engine/bin/nervepack-mcp"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_MCP_REGISTRY="$tmp/registry"; : > "$NP_MCP_REGISTRY"

# --- stub claude: a minimal `claude mcp add|remove` registry ----------------
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
# Recognize only: `claude mcp add <name> ... -- <cmd>` and `claude mcp remove <name> ...`
reg="$NP_MCP_REGISTRY"
if [[ "$1" == "mcp" && "$2" == "add" ]]; then
  name="$3"; shift 3
  # the command is everything after the literal `--`
  cmd=""; seen=0
  for a in "$@"; do
    if [[ $seen == 1 ]]; then cmd="$a"; break; fi
    [[ "$a" == "--" ]] && seen=1
  done
  printf '%s\t%s\n' "$name" "$cmd" >> "$reg"
  exit 0
elif [[ "$1" == "mcp" && "$2" == "remove" ]]; then
  name="$3"
  if [[ -f "$reg" ]]; then _tab="$(printf '\t')"; grep -v "^${name}${_tab}" "$reg" > "$reg.tmp" 2>/dev/null || true; mv "$reg.tmp" "$reg"; fi
  exit 0
fi
exit 0
STUB
chmod +x "$tmp/claude"
export PATH="$tmp:$PATH"

bash "$INSTALL" >/dev/null
n="$(awk -F'\t' '$1=="nervepack"{c++} END{print c+0}' "$NP_MCP_REGISTRY")"
[[ "$n" == "1" ]] || { echo "FAIL: after first run, nervepack entries=$n (want 1)"; cat "$NP_MCP_REGISTRY"; exit 1; }
got="$(awk -F'\t' '$1=="nervepack"{print $2; exit}' "$NP_MCP_REGISTRY")"
[[ "$got" == "$LAUNCHER" ]] || { echo "FAIL: launcher path=$got (want $LAUNCHER)"; exit 1; }

bash "$INSTALL" >/dev/null   # idempotent: remove-then-add
n2="$(awk -F'\t' '$1=="nervepack"{c++} END{print c+0}' "$NP_MCP_REGISTRY")"
[[ "$n2" == "1" ]] || { echo "FAIL: after second run, nervepack entries=$n2 (want 1, no dup)"; cat "$NP_MCP_REGISTRY"; exit 1; }
echo "PASS test_install_mcp"
