#!/usr/bin/env bash
# np-test: aggregate-commit-scope | 73-aggregate's commit is path-limited and change-guarded
# Regression for issue #11: the metrics cron finished with a pathspec-LESS `git commit`,
# so when it ran while another session had files staged in the shared working tree, it
# swept that session's staged work into a mislabeled `evaluator(metrics)` commit (and
# nearly pushed it to main). Two properties this test enforces:
#   (A) An unrelated staged file is NOT swept into the metrics commit (path-limit).
#   (B) A run that changes none of the metrics paths makes NO commit at all (change-guard).
# The cron must stay fail-open throughout (never abort a session).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"     # engine/setup/
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Minimal nervepack-shaped repo: engine code under engine/setup/, content (the metrics
# data file) routed to the repo root via NP_CONTENT_DIR. Mirrors the real split layout
# and the skill-maintain test's repo shape.
NP="$tmp/np"; mkdir -p "$NP/engine/setup" "$NP/dashboard/data"
cp "$SETUP/73-aggregate-metrics.sh" "$SETUP/np-toggle-lib.sh" \
   "$SETUP/np-content-lib.sh" "$NP/engine/setup/"
printf 'evaluator|shared|runtime|on|retain_days=0\n' > "$NP/engine/setup/toggles.conf"
# dashboard OFF (via local override): skip the dashboard rebuild — no build.py in this
# minimal repo. The commit's path-limit is what we test; .js regen is a separate,
# dashboard-gated concern. metrics.js is seeded committed below so the cron's `git add`
# of both paths finds it.
printf 'evaluator.dashboard=off\n' > "$tmp/local"
# A bare origin so `git push origin HEAD:main` is hermetic (no network); push success
# is irrelevant to the assertions — we inspect the local commit either way.
ORIGIN="$tmp/origin.git"; git init -q --bare "$ORIGIN"
# Seed BOTH committed metrics files (the dashboard build normally produces metrics.js);
# the cron's `git add` of both paths needs them to exist or it stages nothing.
( cd "$NP" && git init -q && git config user.email "t@t" && git config user.name "Pat" \
    && git remote add origin "$ORIGIN" \
    && : > dashboard/data/metrics.jsonl \
    && printf 'window.NP_METRICS=[];\n' > dashboard/data/metrics.js \
    && git add dashboard/data/metrics.jsonl dashboard/data/metrics.js && git commit -qm init \
    && git push -q origin HEAD:main )

INBOX="$tmp/inbox"; mkdir -p "$INBOX"
run_agg() {  # runs the cron's real commit path (NOT NP_AGG_NO_COMMIT)
  local rc=0
  # `|| rc=$?` so `set -e` doesn't abort before we can assert fail-open.
  ( cd "$NP" && EVAL_INBOX="$INBOX" NP_CONTENT_DIR="$NP" \
      NP_TOGGLES_CONF="$NP/engine/setup/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
      bash engine/setup/73-aggregate-metrics.sh ) >/dev/null 2>&1 || rc=$?
  # fail-open: the cron must never abort a session, even if a step inside fails.
  [[ $rc -eq 0 ]] || { echo "FAIL: cron exited non-zero ($rc) — fail-open violated"; exit 1; }
}

# ---------------------------------------------------------------------------
# (A) Concurrent session stages an unrelated file. A real-record run commits the
#     metrics — but must NOT sweep the unrelated staged file into that commit.
# ---------------------------------------------------------------------------
printf '{"session_id":"a","contribution_score":50}\n' > "$INBOX/2026-06-17.jsonl"
echo "concurrent work in progress" > "$NP/UNRELATED_WIP.txt"
( cd "$NP" && git add UNRELATED_WIP.txt )   # another session's staged file
run_agg

head_sha="$(cd "$NP" && git rev-parse HEAD)"
# The metrics commit must exist (a real record was drained)...
( cd "$NP" && git log -1 --format='%s' "$head_sha" | grep -q 'evaluator(metrics): daily batch' ) \
  || { echo "FAIL: metrics commit not created for a real-record run"; exit 1; }
# ...and it must contain ONLY metrics paths — never the unrelated staged file.
committed="$(cd "$NP" && git show --name-only --format= "$head_sha")"
if grep -q 'UNRELATED_WIP.txt' <<<"$committed"; then
  echo "FAIL: metrics commit SWEPT the concurrent session's staged file:"; echo "$committed"; exit 1
fi
# The unrelated file must remain staged (untouched), available to its owning session.
( cd "$NP" && git diff --cached --name-only | grep -q 'UNRELATED_WIP.txt' ) \
  || { echo "FAIL: unrelated staged file was stolen from the index"; exit 1; }

# ---------------------------------------------------------------------------
# (B) Change-guard: a run that touches NONE of the metrics paths makes NO commit.
#     (Empty inbox => `0 record(s)` => the historic empty/mislabeled commit.)
# ---------------------------------------------------------------------------
before="$(cd "$NP" && git rev-parse HEAD)"
rm -f "$INBOX"/*.jsonl 2>/dev/null || true   # empty inbox -> nothing new staged
echo "more concurrent work" > "$NP/UNRELATED_WIP2.txt"
( cd "$NP" && git add UNRELATED_WIP2.txt )
run_agg
after="$(cd "$NP" && git rev-parse HEAD)"
[[ "$before" == "$after" ]] \
  || { echo "FAIL: no-change run created a commit (HEAD moved $before -> $after)"; \
       ( cd "$NP" && git show --stat --format='%s' HEAD ); exit 1; }

echo "PASS test_aggregate_commit_scope"
