#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRUB="$HERE/../../episodic-scrub.sh"

out="$(printf 'use sk-ABCDEFGHIJKLMNOPQRSTUV and ghp_ABCDEFGHIJKLMNOPQRSTU now\n' | "$SCRUB")"
echo "$out" | grep -q 'REDACTED' || { echo "FAIL: secret not redacted: $out"; exit 1; }
echo "$out" | grep -q 'sk-ABCDEFG' && { echo "FAIL: raw OpenAI key leaked: $out"; exit 1; }
echo "$out" | grep -q 'ghp_ABCDEFG' && { echo "FAIL: raw GitHub token leaked: $out"; exit 1; }

clean="$(printf 'just normal text about oauth login\n' | "$SCRUB")"
[[ "$clean" == "just normal text about oauth login" ]] || { echo "FAIL: clean text altered: $clean"; exit 1; }

# Broadened denylist: fine-grained PAT, other gh* prefixes, aws secret, Bearer, key=value
pat="$(printf 'tok github_pat_0123456789ABCDEFGHIJ_klmnopqrstuvwx end\n' | "$SCRUB")"
echo "$pat" | grep -q 'github_pat_0123' && { echo "FAIL: fine-grained PAT leaked: $pat"; exit 1; }
echo "$pat" | grep -q 'REDACTED' || { echo "FAIL: PAT not redacted: $pat"; exit 1; }

gho="$(printf 'tok gho_ABCDEFGHIJKLMNOPQRSTUVWX end\n' | "$SCRUB")"
echo "$gho" | grep -q 'gho_ABCDEFG' && { echo "FAIL: gho_ token leaked: $gho"; exit 1; }

pw="$(printf 'config password=Sup3rSecretValue here\n' | "$SCRUB")"
echo "$pw" | grep -q 'Sup3rSecretValue' && { echo "FAIL: password value leaked: $pw"; exit 1; }

br="$(printf 'header Bearer abcdef123456ghijklmno end\n' | "$SCRUB")"
echo "$br" | grep -q 'abcdef123456ghijkl' && { echo "FAIL: bearer token leaked: $br"; exit 1; }

echo "PASS test_scrub"
