#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MATCH="$HERE/../../episodic-match.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/INDEX.md" <<'IDX'
# episodic — topic index
| topic | last_updated | keywords | lines |
|---|---|---|---:|
| auth-patterns | 2026-06-02 | oauth, login, token, session | 20 |
| meeting-template | 2026-05-30 | agenda, notes, calendar | 12 |
IDX

hit="$(printf 'help me fix the oauth login flow' | "$MATCH" "$tmp/INDEX.md")"
[[ "$hit" == "auth-patterns" ]] || { echo "FAIL: expected auth-patterns, got: [$hit]"; exit 1; }

miss="$(printf 'what is the weather today' | "$MATCH" "$tmp/INDEX.md")"
[[ -z "$miss" ]] || { echo "FAIL: expected no match, got: [$miss]"; exit 1; }

echo "PASS test_match"
