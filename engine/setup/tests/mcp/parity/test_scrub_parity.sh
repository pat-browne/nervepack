#!/usr/bin/env bash
# A/B parity: np_scrub.py must produce byte-identical output to episodic-scrub.sh
# across every secret shape it redacts, the backreference-preserving rules
# (aws key / password=…), multi-secret lines, non-matches, and multi-line input.
# Byte-oriented, so no path/CRLF/encoding dialect issues — runs on Linux + the
# Git-bash Windows lane.
#
# The fake secret fixtures are ASSEMBLED FROM PARTS at runtime (prefix vars below)
# so no literal secret string ever appears in this committed file — otherwise
# GitHub push-protection and the PII guard would (correctly) flag them. np_scrub
# still sees the full shape via stdin.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/episodic-scrub.sh"
PY="$SETUP/np_scrub.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_scrub_parity: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0

# Prefixes kept separate from the random tails so no full secret literal is committed.
SK="sk-"; GHP="ghp_"; PAT="github_pat_"; AK="AK""IA"; XOX="xoxb-"; JWT="eyJ"
BEGIN="-----BEGIN RSA "; PK="PRIVATE KEY-----"; TAIL="abcdefghij0123456789ABCD"
G36="abcdefghijklmnopqrstuvwxyz0123456789"

cmp_scrub() {  # $1=label  $2=input (stdin)
  printf '%s' "$2" | bash    "$SH" > "$tmp/b.out" 2>/dev/null
  printf '%s' "$2" | python3 "$PY" > "$tmp/p.out" 2>/dev/null
  if ! cmp -s "$tmp/b.out" "$tmp/p.out"; then
    echo "FAIL [$1]:"; echo "--- bash ---"; cat "$tmp/b.out"; echo "--- python ---"; cat "$tmp/p.out"
    fails=$((fails+1))
  fi
}

cmp_scrub "openai key"    "key is ${SK}${TAIL} here"
cmp_scrub "github pat"    "${PAT}11ABCDEFG0123456789_abcdefghijklmnop"
cmp_scrub "gh token"      "${GHP}${G36}"
cmp_scrub "aws akid"      "id ${AK}0123456789ABCDEF end"
cmp_scrub "slack xoxb"    "${XOX}1234567890-abcdefghijklmnop"
cmp_scrub "aws secret kv" "AWS_SECRET_ACCESS_KEY = ${G36}${G36}abcd"
cmp_scrub "bearer"        "Authorization: Bearer abcdef.ghijkl-mnopqrstuv"
cmp_scrub "password kv"   'password: "hunter2secret"'
cmp_scrub "token kv"      "token=abcdef123456"
cmp_scrub "api_key kv"    "api_key: ${SK}zzzzzzzzzzzzzzzzzzzz"
cmp_scrub "jwt"           "tok ${JWT}abcdefgh.ijklmnopqr.stuvwxyz01 done"
cmp_scrub "private key"   "${BEGIN}${PK}"
cmp_scrub "no secret"     "just a normal sentence with password but short pw=abc"
cmp_scrub "two on a line" "${SK}${TAIL} and ${GHP}${G36}"
cmp_scrub "json envelope" "{\"body\":\"we set token=supersecretvalue and used ${SK}${TAIL}\"}"
cmp_scrub "multiline"     "$(printf 'line one has %s%s\nline two clean\nline three %s%s' "$SK" "$TAIL" "$GHP" "$G36")"
cmp_scrub "empty"         ""

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_scrub_parity: $fails mismatch(es)"; exit 1
fi
echo "PASS test_scrub_parity"
