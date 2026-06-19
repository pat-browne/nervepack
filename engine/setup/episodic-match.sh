#!/usr/bin/env bash
# Keyword-match a prompt (stdin) against episodic/INDEX.md ($1).
# Prints matching topic slugs, one per line, highest score first.
set -euo pipefail
INDEX="${1:?usage: episodic-match.sh <INDEX.md>}"
[[ -f "$INDEX" ]] || exit 0

prompt=" $(tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' ' ') "

awk -F'|' -v prompt="$prompt" '
  /^[[:space:]]*\|/ {
    # skip header and separator rows
    if ($0 ~ /topic[[:space:]]*\|[[:space:]]*last_updated/) next
    if ($0 ~ /^[[:space:]]*\|[-:[:space:]|]+$/) next
    topic=$2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", topic)
    kw=$4;    gsub(/^[[:space:]]+|[[:space:]]+$/, "", kw)
    if (topic == "" ) next
    n=split(kw, arr, /[,[:space:]]+/); score=0
    for (i=1;i<=n;i++) { k=tolower(arr[i]); if (k!="" && index(prompt, " " k " ")>0) score++ }
    if (score>0) printf "%d\t%s\n", score, topic
  }
' "$INDEX" | sort -rn | cut -f2
