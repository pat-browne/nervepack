#!/usr/bin/env bash
# np-test: nervepack-session-directive | team-aware routing fragment merge
# The content-fed routing fragment (directive-routing.md) is fed from ALL merge
# roots (team[0..n] > personal) via np_merge_roots, not personal-only — so a team
# overlay's domain-skill routing reaches sessions. Highest-precedence first (team
# before personal), gated by the `team` toggle, fail-open, byte-stable (invariant 11).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; SETUP="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack" "$tmp/personal" "$tmp/team"
printf '## Personal routing\n| Ptrig | Pskill |\n' > "$tmp/personal/directive-routing.md"
printf '## Team routing\n| Ttrig | Tskill |\n'     > "$tmp/team/directive-routing.md"
: > "$tmp/toggles.conf"
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"
export NP_CONTENT_DIR="$tmp/personal" NP_TEAM_DIR="$tmp/team"
run(){ bash "$SETUP/nervepack-session-directive.sh"; }
# byte offset of the first occurrence of $2 in $1 (length grows -> later position)
pos(){ local pre="${1%%"$2"*}"; printf '%s' "${#pre}"; }

# (1) team on -> BOTH fragments appended, team BEFORE personal, byte-stable
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"
o1="$(run)"; o2="$(run)"
[[ "$o1" == "$o2" ]] || { echo "FAIL: composed output not byte-stable"; exit 1; }
echo "$o1" | grep -q "Team routing"     || { echo "FAIL: team fragment not appended"; exit 1; }
echo "$o1" | grep -q "Personal routing" || { echo "FAIL: personal fragment not appended"; exit 1; }
[[ "$(pos "$o1" "Team routing")" -lt "$(pos "$o1" "Personal routing")" ]] \
  || { echo "FAIL: team routing must precede personal (highest-precedence first)"; exit 1; }

# (2) team OFF -> only the personal fragment (team dropped)
printf 'team=off\n' > "$NP_TOGGLES_LOCAL"
o="$(run)"
echo "$o" | grep -q "Personal routing" || { echo "FAIL: personal fragment missing with team off"; exit 1; }
echo "$o" | grep -q "Team routing"     && { echo "FAIL: team fragment leaked with team off"; exit 1; }

# (3) fail-open: no fragments -> engine directive only, no error, no phantom routing
rm -f "$tmp/personal/directive-routing.md" "$tmp/team/directive-routing.md"
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"
o="$(run)" || { echo "FAIL: emitter errored with no fragments"; exit 1; }
echo "$o" | grep -qE "Team routing|Personal routing" && { echo "FAIL: phantom routing with no fragments"; exit 1; }
echo "$o" | python3 -c "import sys,json; json.load(sys.stdin)" >/dev/null 2>&1 \
  || { echo "FAIL: emitter stdout is not valid JSON"; exit 1; }

echo "PASS test_directive_team_routing"
