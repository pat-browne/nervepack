#!/usr/bin/env bash
# np-test: mcp-install | happy
# The guided installer (np-mcp-install.sh): feed it answers on stdin with a stubbed
# `claude` + hermetic HOME, and assert the real side effects — it writes the content-dir
# and team-dir config, enables the team toggle, registers the MCP server, and runs the
# doctor. Also covers the non-interactive path (empty stdin -> defaults, no team).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
INSTALL="$SETUP/np-mcp-install.sh"
fail=0
chk() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }

bash -n "$INSTALL" || { echo "FAIL: syntax error"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
home="$tmp/home"; content="$tmp/content"; team="$tmp/team"
mkdir -p "$home" "$content" "$team" "$tmp/bin"

# stub claude — records `mcp add/remove` so we can prove the server was registered
cat > "$tmp/bin/claude" <<STUB
#!/usr/bin/env bash
echo "\$*" >> "$tmp/claude-calls"
exit 0
STUB
chmod +x "$tmp/bin/claude"

run() {  # stdin answers piped in by the caller
  HOME="$home" PATH="$tmp/bin:$PATH" bash "$INSTALL"
}

# --- interactive path: content + team provided ---
out="$(printf '%s\n%s\n' "$content" "$team" | run 2>&1)"

cfg="$home/.config/nervepack"
chk "content-dir written with the given path" "[ \"\$(cat '$cfg/content-dir' 2>/dev/null)\" = '$content' ]"
chk "team-dir written with the given path"    "[ \"\$(cat '$cfg/team-dir' 2>/dev/null)\" = '$team' ]"
# team is a shared, on-by-default toggle — the installer must NOT flip it (that would
# commit to the engine repo); configuring team-dir is what activates the overlay.
chk "installer did not write a local team toggle" "[ ! -f '$cfg/toggles.local' ] || ! grep -q 'team' '$cfg/toggles.local'"
chk "MCP server registered (claude mcp add)"  "grep -q 'mcp add nervepack' '$tmp/claude-calls' 2>/dev/null"
chk "doctor ran (capability output present)"  "printf '%s' \"\$out\" | grep -qiE 'doctor|knowledge|llm-cli|capabilit'"

# --- non-interactive path: empty stdin -> engine-root default, no team, no crash ---
rm -rf "$home"; mkdir -p "$home"; : > "$tmp/claude-calls"
out2="$(printf '' | run 2>&1)"; rc=$?
chk "empty stdin still exits 0"               "[ '$rc' = 0 ]"
chk "no content-dir written on blank default" "[ ! -f '$home/.config/nervepack/content-dir' ]"
chk "no team-dir written on blank default"    "[ ! -f '$home/.config/nervepack/team-dir' ]"
chk "still registered the server"             "grep -q 'mcp add nervepack' '$tmp/claude-calls' 2>/dev/null"

[ $fail -eq 0 ] && echo "PASS test_mcp_install" || { echo "FAIL test_mcp_install"; exit 1; }
