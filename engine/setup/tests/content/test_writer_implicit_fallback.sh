#!/usr/bin/env bash
# np-test: writer-implicit-fallback | personal-content writers skip the commit on the
#          IMPLICIT engine-root fallback, but still commit on an EXPLICIT overlay
# Regression for issue #12: np_content_dir silently falls back to the engine repo root
# when NP_CONTENT_DIR is unset AND ~/.config/nervepack/content-dir is absent. On a split
# layout mid-onboard that routes personal-content commits (metrics, episodic, etc.) into
# the PII-clean engine repo. The fix: the personal-content writers gate on
# np_content_is_explicit and SKIP their commit (fail-open, log, exit 0) on the implicit
# fallback — while a DELIBERATE single-repo user (config file present, even pointing at
# the engine root) still commits normally.
#
# 73-aggregate-metrics.sh is the deterministic, no-LLM writer, so it's the one we can
# drive end-to-end without stubbing a model. The guard it gains lives in the shared
# resolver (np-content-lib.sh), so proving it here proves the shared mechanism the
# agentic writers (71/72/75) gate on too.
#
# Properties enforced:
#   (A) IMPLICIT fallback (env unset + no config) => NO commit (engine stays clean).
#   (B) EXPLICIT overlay via NP_CONTENT_DIR => commit happens.
#   (C) DELIBERATE single-repo (config file == engine root, set on purpose) => commit
#       happens — legacy single-repo layout preserved.
# Fail-open throughout: the cron must never abort, even when it skips.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"     # engine/setup/
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Minimal nervepack-shaped repo (mirrors test_aggregate_commit_scope.sh's shape).
NP="$tmp/np"; mkdir -p "$NP/engine/setup" "$NP/dashboard/data"
cp "$SETUP/73-aggregate-metrics.sh" "$SETUP/np-toggle-lib.sh" \
   "$SETUP/np-content-lib.sh" "$NP/engine/setup/"
printf 'evaluator|shared|runtime|on|retain_days=0\n' > "$NP/engine/setup/toggles.conf"
printf 'evaluator.dashboard=off\n' > "$tmp/local"   # no build.py in this minimal repo
ORIGIN="$tmp/origin.git"; git init -q --bare "$ORIGIN"
( cd "$NP" && git init -q && git config user.email "t@t" && git config user.name "Pat" \
    && git remote add origin "$ORIGIN" \
    && : > dashboard/data/metrics.jsonl \
    && printf 'window.NP_METRICS=[];\n' > dashboard/data/metrics.js \
    && git add dashboard/data/metrics.jsonl dashboard/data/metrics.js && git commit -qm init \
    && git push -q origin HEAD:main )

INBOX="$tmp/inbox"; mkdir -p "$INBOX"

# Run the cron's REAL commit path (NOT NP_AGG_NO_COMMIT) with a controllable HOME (for
# the config-file cases) and content-dir env. The content dir is ALWAYS the engine root
# $NP here — the only thing we vary is whether that resolution is explicit or implicit,
# which is exactly the distinction the fix turns on.
run_agg() {  # $@ = extra `KEY=VALUE` env entries passed to `env`
  local rc=0
  ( cd "$NP" && env "$@" EVAL_INBOX="$INBOX" \
      NP_TOGGLES_CONF="$NP/engine/setup/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
      bash engine/setup/73-aggregate-metrics.sh ) >/dev/null 2>&1 || rc=$?
  [[ $rc -eq 0 ]] || { echo "FAIL: cron exited non-zero ($rc) — fail-open violated"; exit 1; }
}

seed_record() { printf '{"session_id":"%s","contribution_score":50}\n' "$1" > "$INBOX/rec.jsonl"; }

# ---------------------------------------------------------------------------
# (A) IMPLICIT fallback: NP_CONTENT_DIR unset + HOME with no content-dir config.
#     A real record is drained, but because the dir resolved via the silent
#     engine-root fallback, the writer MUST skip the commit (no engine pollution).
# ---------------------------------------------------------------------------
EMPTY_HOME="$tmp/home_implicit"; mkdir -p "$EMPTY_HOME/.config/nervepack"  # dir exists, file absent
seed_record a
before="$(cd "$NP" && git rev-parse HEAD)"
# unset NP_CONTENT_DIR; point HOME at a config-less home so the resolver falls back.
# `env -u NP_CONTENT_DIR` scrubs any value inherited from the suite's own environment.
unset NP_CONTENT_DIR
run_agg -u NP_CONTENT_DIR "HOME=$EMPTY_HOME"
after="$(cd "$NP" && git rev-parse HEAD)"
[[ "$before" == "$after" ]] \
  || { echo "FAIL (A): implicit-fallback run created a commit (HEAD moved $before -> $after)"; \
       ( cd "$NP" && git show --stat --format='%s' HEAD ); exit 1; }
# The metrics file should NOT have been committed; the drained record may have been
# appended to the working tree, but it must remain UNCOMMITTED (engine stays clean).
( cd "$NP" && git log -1 --format='%s' HEAD | grep -q 'evaluator(metrics)' ) \
  && { echo "FAIL (A): a metrics commit landed despite the implicit fallback"; exit 1; }

# ---------------------------------------------------------------------------
# (B) EXPLICIT overlay via NP_CONTENT_DIR (== engine root, set explicitly): commit.
# ---------------------------------------------------------------------------
# Reset ONLY the committed metrics paths (a plain `git clean -fdq` would also delete the
# untracked engine/setup/*.sh we copied in, leaving bash with nothing to run).
( cd "$NP" && git checkout -q -- dashboard/data/metrics.jsonl dashboard/data/metrics.js )
seed_record b
before="$(cd "$NP" && git rev-parse HEAD)"
run_agg "NP_CONTENT_DIR=$NP"   # (B) explicit overlay
after="$(cd "$NP" && git rev-parse HEAD)"
[[ "$before" != "$after" ]] \
  || { echo "FAIL (B): explicit NP_CONTENT_DIR overlay did NOT commit (HEAD unchanged)"; exit 1; }
( cd "$NP" && git log -1 --format='%s' HEAD | grep -q 'evaluator(metrics): daily batch' ) \
  || { echo "FAIL (B): explicit-overlay run did not produce the metrics commit"; exit 1; }

# ---------------------------------------------------------------------------
# (C) DELIBERATE single-repo legacy: config file present, pointing at the engine root
#     ON PURPOSE. NP_CONTENT_DIR unset, but the config makes it explicit => commit.
# ---------------------------------------------------------------------------
( cd "$NP" && git checkout -q -- dashboard/data/metrics.jsonl dashboard/data/metrics.js )
LEGACY_HOME="$tmp/home_legacy"; mkdir -p "$LEGACY_HOME/.config/nervepack"
printf '%s\n' "$NP" > "$LEGACY_HOME/.config/nervepack/content-dir"   # deliberate single-repo
seed_record c
before="$(cd "$NP" && git rev-parse HEAD)"
run_agg -u NP_CONTENT_DIR "HOME=$LEGACY_HOME"   # (C) deliberate single-repo via config file
after="$(cd "$NP" && git rev-parse HEAD)"
[[ "$before" != "$after" ]] \
  || { echo "FAIL (C): deliberate single-repo (config==engine root) did NOT commit — legacy broken"; exit 1; }
( cd "$NP" && git log -1 --format='%s' HEAD | grep -q 'evaluator(metrics): daily batch' ) \
  || { echo "FAIL (C): legacy single-repo run did not produce the metrics commit"; exit 1; }

echo "PASS test_writer_implicit_fallback"
