#!/usr/bin/env bash
# np-test: onboard | starter-adopt
# The optional, declinable "adopt nervepack-content-example as your starter content
# overlay" step in np-mcp-install.sh. Declining (or any non-interactive default) must
# be a clean no-op -- the engine never requires the generic starter pack. Adopting
# clones the pack and points ~/.config/nervepack/content-dir at it. Exercised in
# isolation via --starter-only so the test doesn't have to stub the whole installer
# (claude CLI, doctor, path-check) or touch the network.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; SETUP="$HERE/../.."
INSTALL="$SETUP/np-mcp-install.sh"
fail=0
chk() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }

bash -n "$INSTALL" || { echo "FAIL: syntax error"; exit 1; }

# --- decline: leaves no content-dir config, exits 0 ---------------------------------
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
HOME="$tmp" NP_STARTER_ADOPT_FORCE=decline bash "$INSTALL" --starter-only >/dev/null 2>&1
rc=$?
chk "decline exits 0"                 "[ $rc -eq 0 ]"
chk "decline writes no content-dir"   "[ ! -f '$tmp/.config/nervepack/content-dir' ]"

# --- adopt: network-free via a local git repo standing in for the example pack -----
tmp2="$(mktemp -d)"; trap 'rm -rf "$tmp" "$tmp2"' EXIT
src="$tmp2/fake-content-example"
mkdir -p "$src"
git -C "$src" init -q
git -C "$src" -c user.email=t@t -c user.name=t commit --allow-empty -q -m init
dest="$tmp2/home/Code/starter-content"

HOME="$tmp2/home" NP_STARTER_ADOPT_FORCE=adopt NP_STARTER_ADOPT_SOURCE="$src" \
  NP_STARTER_ADOPT_PATH="$dest" bash "$INSTALL" --starter-only >/dev/null 2>&1
rc2=$?
chk "adopt exits 0"          "[ $rc2 -eq 0 ]"
chk "adopt writes content-dir -> chosen path" \
  "[ \"\$(cat '$tmp2/home/.config/nervepack/content-dir' 2>/dev/null)\" = '$dest' ]"
chk "adopt actually cloned the source into dest" "[ -d '$dest/.git' ]"

# --- already-configured overlay: the offer is skipped even on force=adopt ----------
tmp3="$(mktemp -d)"; trap 'rm -rf "$tmp" "$tmp2" "$tmp3"' EXIT
mkdir -p "$tmp3/.config/nervepack"
printf '%s\n' "/already/configured" > "$tmp3/.config/nervepack/content-dir"
HOME="$tmp3" NP_STARTER_ADOPT_FORCE=adopt bash "$INSTALL" --starter-only >/dev/null 2>&1
rc3=$?
chk "already-configured overlay: exits 0" "[ $rc3 -eq 0 ]"
chk "already-configured overlay: config left untouched" \
  "[ \"\$(cat '$tmp3/.config/nervepack/content-dir')\" = '/already/configured' ]"

# --- regression: the starter offer must not perturb the guided-install stdin
# sequence -----------------------------------------------------------------------
# Drive the FULL installer (not --starter-only) with the documented guided-install
# pattern: a blank content-dir answer, then a team-dir path on the next line.
# NP_STARTER_ADOPT_FORCE is deliberately UNSET (real interactive use) so
# offer_starter_adopt (if still wired inside step 1) issues its own `ask()` and
# swallows the team-dir line meant for step 2. Stub `claude` off PATH — a fresh
# PATH without git/coreutils dirs would break the script's own commands, so we
# stub `claude` (used by 58-install-mcp.sh / the doctor's registration check)
# rather than removing real PATH, mirroring test_mcp_install.sh.
tmp4="$(mktemp -d)"; trap 'rm -rf "$tmp" "$tmp2" "$tmp3" "$tmp4"' EXIT
home4="$tmp4/home"; team4="$tmp4/team"; mkdir -p "$home4" "$team4" "$tmp4/bin"
cat > "$tmp4/bin/claude" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "$tmp4/bin/claude"

out4="$(printf '\n%s\n' "$team4" | HOME="$home4" PATH="$tmp4/bin:$PATH" \
  env -u NP_STARTER_ADOPT_FORCE bash "$INSTALL" 2>&1)"
chk "guided flow: team-dir IS written (not swallowed by the starter offer)" \
  "[ \"\$(cat '$home4/.config/nervepack/team-dir' 2>/dev/null)\" = '$team4' ]"

[ $fail -eq 0 ] && echo "PASS test_starter_adopt" || { echo "FAIL test_starter_adopt"; exit 1; }
