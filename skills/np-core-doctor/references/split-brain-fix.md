# Fixing a content-checkout split-brain

Triggered from [[np-core-doctor]] when `main..HEAD` and `HEAD..origin/main` both
show commits on the content repo.

## 1. Stop the crons first

Concurrent writes during the merge corrupt the result. Turn off both writers on
this machine:
```
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py" toggle memory.maintain off
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py" toggle evaluator.aggregate off
```
Re-enable both (`... on`) once the merge below is pushed.

## 2. Merge, from the stale branch

```
git -C "$CONTENT" merge origin/main
```
If it merges clean, skip to step 5.

## 3. If it conflicts

The conflicts land in generated files: `metrics.jsonl`, `dashboard/data/metrics.js`,
`INDEX.md`. Don't pick a side. A picked side silently drops the other branch's
real session data. See [[np-kb-git-gotchas]] (generated-file conflicts) for why.

**`metrics.jsonl`** is one JSON object per line, keyed by `session_id` and `ts`.
Union both sides, dedupe exact lines, sort by `ts`, then prune anything older
than `evaluator.retain_days` (default 90 days). That's the same rule the daily
aggregate job applies every normal run:
```
python3 - <<'PY'
import json, os, subprocess, datetime

content = os.environ["CONTENT"]
path = "dashboard/data/metrics.jsonl"

def side(rev):
    out = subprocess.run(["git", "-C", content, "show", f"{rev}:{path}"],
                          capture_output=True, text=True, check=True).stdout
    return out.splitlines()

lines = set(side(":2")) | set(side(":3"))  # :2 ours, :3 theirs
cutoff = (datetime.datetime.now(datetime.timezone.utc)
          - datetime.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")

kept = []
for line in lines:
    if not line.strip():
        continue
    rec = json.loads(line)
    if rec.get("ts", "") >= cutoff:
        kept.append((rec["ts"], line))
kept.sort()

with open(os.path.join(content, path), "w") as fh:
    fh.write("\n".join(line for _, line in kept) + "\n")
PY
```

**`metrics.js` and `INDEX.md`** are pure derived output. Regenerate them, don't
merge them.

The index script takes no arguments. It resolves `NP_CONTENT_DIR` itself, the
same way step 0's content-dir call did, so it writes to the right tree as long
as that variable is still set in this shell:
```
python3 "${NP_DIR:-$HOME/Code/nervepack}/dashboard/build.py" "$CONTENT/dashboard/data/metrics.jsonl" "$CONTENT/dashboard/data/metrics.js"
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/setup/np_generate_index.py"
```

## 4. Verify the rebuild before committing

```
git -C "$CONTENT" status --porcelain
```
Every path touched above (`metrics.jsonl`, `metrics.js`, `INDEX.md`) should show
as modified, nothing else. If either regeneration script printed a traceback,
fix that first. Do not commit a partial rebuild.

## 5. Commit and finish the merge

Name the touched paths explicitly rather than `git add -A`, per this repo's
`AGENTS.md` convention against a bare, pathspec-less add:
```
git -C "$CONTENT" add dashboard/data/metrics.jsonl dashboard/data/metrics.js INDEX.md
git -C "$CONTENT" commit -m "merge: reconcile main and the stale branch"
git -C "$CONTENT" checkout main
git -C "$CONTENT" merge --ff-only "$STALE_BRANCH"
```
`merge --ff-only` errors instead of doing anything silent if the branches still
diverge here. That means step 2's merge commit isn't actually on top of the
current `origin/main`. Re-run from step 2 on `$STALE_BRANCH`, since
`origin/main` can move while you work.

## 6. Publish and clean up

```
git -C "$CONTENT" push origin main
git -C "$CONTENT" branch -D "$STALE_BRANCH"
```
