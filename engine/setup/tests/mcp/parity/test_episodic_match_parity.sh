#!/usr/bin/env bash
# A/B parity: np_episodic_match.py must produce byte-identical stdout to
# episodic-match.sh (the bash original) across an INDEX/prompt fixture table —
# header/separator skipping, scoring, tie-break ordering, hyphenated keywords
# (which never match), the markdown-link topic-cell form, and missing index.
#
# Requires bash (it compares against it), so it runs on Linux + the Git-bash
# Windows lane, not the bash-free lane.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/episodic-match.sh"
PY="$SETUP/np_episodic_match.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_episodic_match_parity: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0

# Compare bash vs python for a given index file + prompt (byte-identical stdout).
cmp_match() {  # $1=index path  $2=prompt
  printf '%s' "$2" | bash "$SH" "$1" > "$tmp/b.out" 2>/dev/null
  printf '%s' "$2" | python3 "$PY" "$1" > "$tmp/p.out" 2>/dev/null
  if ! cmp -s "$tmp/b.out" "$tmp/p.out"; then
    echo "FAIL prompt='$2' index=$(basename "$1"): bash=[$(tr '\n' ',' < "$tmp/b.out")] python=[$(tr '\n' ',' < "$tmp/p.out")]"
    fails=$((fails+1))
  fi
}

# --- Fixture 1: realistic markdown-link topic cells (mirrors a real episodic INDEX) ---
cat > "$tmp/link.md" <<'IDX'
# episodic — topic index

| topic | last_updated | keywords | lines |
|---|---|---|---:|
| [chrome-extensions](chrome-extensions.md) | 2026-06-05 | chrome-web-store, mv3, screenshots, packaging, shell | 13 |
| [display-config](display-config.md) | 2026-06-10 | gnome, monitor, dbus, ultrawide | 24 |
| [nervepack](nervepack.md) | 2026-06-17 | nervepack, episodic, hooks, sync, automation, monitor | 186 |
IDX
cmp_match "$tmp/link.md" "nervepack hooks sync"          # nervepack row, score 3
cmp_match "$tmp/link.md" "monitor"                       # tie: two rows score 1 -> tie-break order
cmp_match "$tmp/link.md" "gnome monitor dbus"            # display-config score 3, nervepack score 1
cmp_match "$tmp/link.md" "nothing matches here"          # empty
cmp_match "$tmp/link.md" "MV3 Screenshots PACKAGING"     # case-insensitive, score 3
cmp_match "$tmp/link.md" "chrome-web-store"              # hyphenated keyword never matches

# --- Fixture 2: plain-slug topics + duplicate scores for tie-break ---
cat > "$tmp/slug.md" <<'IDX'
| topic | last_updated | keywords |
|---|---|---|
| alpha | 2026-01-01 | red, green, blue |
| bravo | 2026-01-02 | red, green |
| charlie | 2026-01-03 | red |
IDX
cmp_match "$tmp/slug.md" "red"                           # all three score 1 -> tie-break
cmp_match "$tmp/slug.md" "red green"                     # alpha2 bravo2 charlie1
cmp_match "$tmp/slug.md" "red green blue"                # alpha3 bravo2 charlie1

# --- Fixture 3: edge cases ---
printf '' > "$tmp/empty.md"
cmp_match "$tmp/empty.md" "anything"                     # empty file -> no output
cmp_match "$tmp/missing-file.md" "anything"              # missing file -> exit 0, no output
# rows with an empty topic cell must be skipped by both
cat > "$tmp/blank.md" <<'IDX'
| topic | last_updated | keywords |
|---|---|---|
|  | 2026-01-01 | red, blue |
| real | 2026-01-02 | red |
IDX
cmp_match "$tmp/blank.md" "red blue"

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_episodic_match_parity: $fails mismatch(es)"
  exit 1
fi
echo "PASS test_episodic_match_parity"
