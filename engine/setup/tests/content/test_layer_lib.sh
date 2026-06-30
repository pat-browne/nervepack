#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
LIB="$S/np-layer-lib.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"; mkdir -p "$tmp/personal" "$tmp/team"
export NP_TOGGLES_CONF="$S/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
export NP_CONTENT_DIR="$tmp/personal"
fail(){ echo "FAIL: $1"; exit 1; }

# no team -> layers = [personal]; merge_roots = [personal]; mode default override
out="$(bash -c "source '$LIB'; np_content_layers")"
[[ "$out" == "$tmp/personal" ]] || fail "no-team layers: '$out'"
[[ "$(bash -c "source '$LIB'; np_merge_mode")" == override ]] || fail "default mode"
[[ "$(bash -c "source '$LIB'; np_merge_roots")" == "$tmp/personal" ]] || fail "no-team roots"

# team configured + toggle on -> layers = team then personal
export NP_TEAM_DIR="$tmp/team"
got="$(bash -c "source '$LIB'; np_content_layers" | tr '\n' ',')"
[[ "$got" == "$tmp/team,$tmp/personal," ]] || fail "team layers: '$got'"

# team-only mode -> roots = team only
printf 'team=on\nteam.merge=team-only\n' > "$tmp/local"
[[ "$(bash -c "source '$LIB'; np_merge_mode")" == team-only ]] || fail "mode read"
[[ "$(bash -c "source '$LIB'; np_merge_roots")" == "$tmp/team" ]] || fail "team-only roots"

# invalid mode -> override
printf 'team.merge=bogus\n' > "$tmp/local"
[[ "$(bash -c "source '$LIB'; np_merge_mode")" == override ]] || fail "invalid mode -> override"

# team toggle OFF -> team dropped from layers even though NP_TEAM_DIR set
printf 'team=off\n' > "$tmp/local"
[[ "$(bash -c "source '$LIB'; np_content_layers")" == "$tmp/personal" ]] || fail "toggle-off drops team"

# Aliases used by the layer-path assertions below (not defined above, so set them here).
LLIB="$S/np-layer-lib.sh"
CLIB="$S/np-content-lib.sh"
ov="$tmp/layer-ov"; mkdir -p "$ov"

# --- np_layer_roots maps each merge root to memory/<layer> ------------------
out="$(NP_CONTENT_DIR="$ov" bash -c 'source "'"$LLIB"'"; np_layer_roots playbooks')"
[ "$out" = "$ov/memory/playbooks" ] \
  || { echo "FAIL np_layer_roots: got [$out] want [$ov/memory/playbooks]"; exit 1; }
# --- np_layer_dir is the single-root form ----------------------------------
out="$(NP_CONTENT_DIR="$ov" bash -c 'source "'"$CLIB"'"; np_layer_dir strategies')"
[ "$out" = "$ov/memory/strategies" ] \
  || { echo "FAIL np_layer_dir: got [$out] want [$ov/memory/strategies]"; exit 1; }
echo "OK np_layer_dir/np_layer_roots"

echo "PASS test_layer_lib"
