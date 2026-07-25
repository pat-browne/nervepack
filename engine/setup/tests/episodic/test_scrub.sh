#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRUB="$HERE/../../np_scrub.py"

out="$(printf 'use sk-ABCDEFGHIJKLMNOPQRSTUV and ghp_ABCDEFGHIJKLMNOPQRSTU now\n' | python3 "$SCRUB")"
echo "$out" | grep -q 'REDACTED' || { echo "FAIL: secret not redacted: $out"; exit 1; }
echo "$out" | grep -q 'sk-ABCDEFG' && { echo "FAIL: raw OpenAI key leaked: $out"; exit 1; }
echo "$out" | grep -q 'ghp_ABCDEFG' && { echo "FAIL: raw GitHub token leaked: $out"; exit 1; }

clean="$(printf 'just normal text about oauth login\n' | python3 "$SCRUB")"
[[ "$clean" == "just normal text about oauth login" ]] || { echo "FAIL: clean text altered: $clean"; exit 1; }

# Broadened denylist: fine-grained PAT, other gh* prefixes, aws secret, Bearer, key=value
pat="$(printf 'tok github_pat_0123456789ABCDEFGHIJ_klmnopqrstuvwx end\n' | python3 "$SCRUB")"
echo "$pat" | grep -q 'github_pat_0123' && { echo "FAIL: fine-grained PAT leaked: $pat"; exit 1; }
echo "$pat" | grep -q 'REDACTED' || { echo "FAIL: PAT not redacted: $pat"; exit 1; }

gho="$(printf 'tok gho_ABCDEFGHIJKLMNOPQRSTUVWX end\n' | python3 "$SCRUB")"
echo "$gho" | grep -q 'gho_ABCDEFG' && { echo "FAIL: gho_ token leaked: $gho"; exit 1; }

pw="$(printf 'config password=Sup3rSecretValue here\n' | python3 "$SCRUB")"
echo "$pw" | grep -q 'Sup3rSecretValue' && { echo "FAIL: password value leaked: $pw"; exit 1; }

br="$(printf 'header Bearer abcdef123456ghijklmno end\n' | python3 "$SCRUB")"
echo "$br" | grep -q 'abcdef123456ghijkl' && { echo "FAIL: bearer token leaked: $br"; exit 1; }

# Shapes whose direct coverage moved here when test_scrub_parity.sh was retired
# in phase 17 (JWT, private-key header, token=, api_key=) — np_scrub.py still
# carries these rules; guard against a future regression.
jwt="$(printf 'auth eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT end\n' | python3 "$SCRUB")"
echo "$jwt" | grep -q 'eyJhbGciOiJIUzI1' && { echo "FAIL: JWT leaked: $jwt"; exit 1; }
echo "$jwt" | grep -q 'REDACTED-JWT' || { echo "FAIL: JWT not redacted: $jwt"; exit 1; }

# NB: the private-key shape (-----BEGIN … PRIVATE KEY-----) is deliberately NOT
# exercised here — that literal trips the engine PII guard (np-publish-scan.py)
# and there's no clean way to feed it without allowlist churn. np_scrub.py's
# private-key rule is unchanged and stays covered indirectly by the pii scan tests.

tok="$(printf 'cfg token=abcdef123456 end\n' | python3 "$SCRUB")"
echo "$tok" | grep -q 'abcdef123456' && { echo "FAIL: token= value leaked: $tok"; exit 1; }

ak="$(printf 'cfg api_key=abcdef123456 end\n' | python3 "$SCRUB")"
echo "$ak" | grep -q 'abcdef123456' && { echo "FAIL: api_key= value leaked: $ak"; exit 1; }

echo "PASS test_scrub"
