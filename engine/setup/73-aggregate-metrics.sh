#!/usr/bin/env bash
# Daily: drain the evaluator inbox into the committed metrics time series, prune
# historic files to the retention cap, then commit + push.
# Deterministic (no LLM). Gated by evaluator.aggregate.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
source "$HERE/np-toggle-lib.sh"
source "$HERE/np-content-lib.sh"
np_enabled evaluator.aggregate || { echo "$(date -u +%FT%TZ) skipped: evaluator.aggregate disabled"; exit 0; }
CONTENT="$(np_content_dir)"
INBOX="${EVAL_INBOX:-$HOME/.cache/nervepack/evaluator-inbox}"
METRICS="${METRICS_FILE:-$CONTENT/dashboard/data/metrics.jsonl}"
RESOLVED="${NP_RESOLVED_SUGGESTIONS:-$CONTENT/dashboard/data/resolved-suggestions.txt}"

shopt -s nullglob
files=("$INBOX"/*.jsonl)
n=0
if [[ ${#files[@]} -gt 0 ]]; then
  mkdir -p "$(dirname "$METRICS")"; touch "$METRICS"
  cat "${files[@]}" >> "$METRICS"
  n=$(cat "${files[@]}" | wc -l)
  rm -f "${files[@]}"
  echo "$(date -u +%FT%TZ) evaluator: appended $n record(s) to $METRICS"
else
  echo "$(date -u +%FT%TZ) evaluator: inbox empty"
fi

# Retention pruning: drop records older than evaluator.retain_days from metrics.jsonl
# and resolved-suggestions.txt. retain_days=0 means unlimited (no pruning). Fail-open:
# records/lines without a parseable timestamp are always kept.
_retain_days="$(np_param evaluator.retain_days 90)"
if [[ "$_retain_days" -gt 0 ]] 2>/dev/null; then
  python3 - "$METRICS" "$_retain_days" <<'PRUNE_PY' || true
import json, os, sys, datetime
metrics_path, retain_days_str = sys.argv[1], sys.argv[2]
try:
    retain_days = int(retain_days_str)
except (ValueError, TypeError):
    sys.exit(0)  # fail-open: unparseable param -> skip prune
cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retain_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
try:
    with open(metrics_path) as fh:
        lines = fh.readlines()
except FileNotFoundError:
    sys.exit(0)
kept = []
pruned = 0
for line in lines:
    stripped = line.strip()
    if not stripped:
        kept.append(line)
        continue
    try:
        rec = json.loads(stripped)
        ts = rec.get("ts", "")
        if ts and ts < cutoff:
            pruned += 1
            continue
    except (ValueError, KeyError):
        pass  # fail-open: unparseable line is kept
    kept.append(line)
if pruned:
    with open(metrics_path, "w") as fh:
        fh.writelines(kept)
    print(f"{os.path.basename(metrics_path)}: pruned {pruned} record(s) older than {retain_days}d", flush=True)
PRUNE_PY

  python3 - "$RESOLVED" "$_retain_days" <<'PRUNE_RES' || true
import os, sys, datetime
resolved_path, retain_days_str = sys.argv[1], sys.argv[2]
try:
    retain_days = int(retain_days_str)
except (ValueError, TypeError):
    sys.exit(0)
cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retain_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
try:
    with open(resolved_path) as fh:
        lines = fh.readlines()
except FileNotFoundError:
    sys.exit(0)
kept = []
pruned = 0
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        kept.append(line)
        continue
    parts = stripped.split("\t", 1)
    if len(parts) == 2:
        ts = parts[1].strip()
        if ts and ts < cutoff:
            pruned += 1
            continue
    # No timestamp (legacy format) or timestamp >= cutoff: keep
    kept.append(line)
if pruned:
    with open(resolved_path, "w") as fh:
        fh.writelines(kept)
    print(f"{os.path.basename(resolved_path)}: pruned {pruned} entry(ies) older than {retain_days}d", flush=True)
PRUNE_RES
fi

# Nothing new to commit and no prune output: skip dashboard rebuild + commit if inbox
# was empty AND retention made no change. The simple approach: always rebuild when we
# had inbox records; otherwise let the dashboard stay as-is (it was already correct).
[[ $n -eq 0 ]] && [[ "${NP_AGG_NO_COMMIT:-0}" == "1" ]] && exit 0

# Regenerate the dashboard data file (gated by evaluator.dashboard, inherits evaluator).
# Window it to the last N sessions (tunable param; default 5) for a recent-perf view.
if np_enabled evaluator.dashboard; then
  METRICS_JS="${CONTENT}/dashboard/data/metrics.js"
  DASHBOARD_SESSIONS="$(np_param evaluator.dashboard_sessions 5)" \
  WIKI_NAV="$(np_param evaluator.wiki_nav on)" \
  WIKI_MERMAID="$(np_param evaluator.wiki_mermaid on)" \
  NP_CONTENT_DIR="$CONTENT" \
  NP_PLAYBOOKS_DIR="$CONTENT/memory/playbooks" \
  NP_STRATEGIES_DIR="$CONTENT/memory/strategies" \
  NP_RESOLVED_SUGGESTIONS="$RESOLVED" \
    python3 "$NP/dashboard/build.py" "$METRICS" "$METRICS_JS" >/dev/null 2>&1 || true
fi

[[ "${NP_AGG_NO_COMMIT:-0}" == "1" ]] && exit 0
# Issue #12: if $CONTENT came from the IMPLICIT engine-root fallback (NP_CONTENT_DIR
# unset AND no ~/.config/nervepack/content-dir), do NOT commit — that would write
# personal metrics into the PII-clean engine repo. Skip the commit/push, log, exit 0
# (fail-open). A deliberate single-repo user opts in via the config file (origin
# 'config') and reaches the commit below as before.
if ! np_content_is_explicit; then
  echo "$(date -u +%FT%TZ) evaluator: content dir is the implicit engine-root fallback — skipping commit (set NP_CONTENT_DIR or ~/.config/nervepack/content-dir)"
  exit 0
fi
# Commit with the machine's GLOBAL git identity (the machine owner) — no bot identity: CLAUDE.md
# requires cron-agent commits authored as that identity, and `git config` here would persist
# into .git/config and mis-author later interactive commits too.
_paths=(dashboard/data/metrics.jsonl dashboard/data/metrics.js)
git -C "$CONTENT" add "${_paths[@]}" >/dev/null 2>&1
# Change-guard: if our own paths staged no change (e.g. a `0 record(s)` run with an
# empty inbox), there is nothing to commit — skip entirely. This alone prevents the
# empty/mislabeled commits that swept concurrent sessions' staged work (issue #11).
if git -C "$CONTENT" diff --cached --quiet -- "${_paths[@]}"; then
  echo "$(date -u +%FT%TZ) evaluator: no metrics change to commit"; exit 0
fi
# Path-LIMIT the commit to our own files so a bare commit can never capture another
# session's staged work in the shared working tree (issue #11). Fail-open preserved
# via the trailing `|| true` — but the guard above is structural, not hidden by it.
git -C "$CONTENT" commit -q -m "evaluator(metrics): daily batch ($(date -u +%F)) — $n record(s)" -- "${_paths[@]}" >/dev/null 2>&1 \
  && git -C "$CONTENT" push -q origin HEAD:main >/dev/null 2>&1 || true
