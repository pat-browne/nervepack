"""Bash-free port of 73-aggregate-metrics.sh -- drains the evaluator inbox into
the committed metrics time series, prunes both metrics.jsonl and
resolved-suggestions.txt to the evaluator.retain_days cap, regenerates the
dashboard data file, and commits + pushes (path-limited, change-guarded --
issue #11: a bare, pathspec-less commit can sweep a concurrent session's
staged work into a mislabeled commit; this never does a bare commit).
Deterministic, no LLM -- already embedded as untestable heredoc Python in the
bash original, so this is a straightforward hoist.

Consumed in-process by hooks/session_flush.py, hooks/open_dashboard.py, and
np-mcp-server.py's _tool_maintain aggregate job. Has its own __main__ entry
point for the `cli.py cron aggregate-metrics` dispatch. stdlib only.
"""
import os
import sys
# self-bootstrap (phase 20b-2): np_toggle/np_content/np_model and the other library
# modules were relocated into engine/nervepack_engine/; add that package dir so this
# script's flat imports of them resolve whether run standalone or imported.
_ENGINE_PKG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nervepack_engine"))
if _ENGINE_PKG not in sys.path:
    sys.path.insert(0, _ENGINE_PKG)

import datetime
import json
import os
import subprocess
import sys
import time

import np_content
import np_toggle
import np_dirs

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.dirname(os.path.dirname(_HERE))


def _prune_metrics(path, retain_days):
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=retain_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    kept, pruned = [], 0
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
            pass
        kept.append(line)
    if pruned:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)


def _prune_resolved(path, retain_days):
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=retain_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    kept, pruned = [], 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            kept.append(line)
            continue
        parts = stripped.split("\t", 1)
        if len(parts) == 2 and parts[1].strip() and parts[1].strip() < cutoff:
            pruned += 1
            continue
        kept.append(line)
    if pruned:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)


def aggregate():
    """Run the full daily aggregate: drain inbox, prune, rebuild dashboard,
    commit+push. Fail-open throughout; returns a short status string."""
    if not np_toggle.enabled("evaluator.aggregate"):
        return "skipped: evaluator.aggregate disabled"

    content = np_content.content_dir()
    inbox = os.environ.get("EVAL_INBOX") or np_dirs.cache_path("evaluator-inbox")
    metrics = os.environ.get("METRICS_FILE") or os.path.join(content, "dashboard", "data", "metrics.jsonl")
    resolved = os.environ.get("NP_RESOLVED_SUGGESTIONS") or os.path.join(
        content, "dashboard", "data", "resolved-suggestions.txt")

    n = 0
    try:
        files = sorted(f for f in os.listdir(inbox) if f.endswith(".jsonl"))
    except OSError:
        files = []
    if files:
        try:
            os.makedirs(os.path.dirname(metrics), exist_ok=True)
            lines = []
            for fname in files:
                with open(os.path.join(inbox, fname), encoding="utf-8") as fh:
                    lines.extend(fh.readlines())
            with open(metrics, "a", encoding="utf-8") as fh:
                fh.writelines(lines)
            n = len(lines)
            for fname in files:
                try:
                    os.remove(os.path.join(inbox, fname))
                except OSError:
                    pass
        except OSError:
            n = 0

    try:
        retain_days = int(np_toggle.param("evaluator.retain_days", "90"))
    except (ValueError, TypeError):
        retain_days = 90
    if retain_days > 0:
        try:
            _prune_metrics(metrics, retain_days)
        except Exception:
            pass
        try:
            _prune_resolved(resolved, retain_days)
        except Exception:
            pass

    no_commit = os.environ.get("NP_AGG_NO_COMMIT") == "1"
    if n == 0 and no_commit:
        return "no-op"

    if np_toggle.enabled("evaluator.dashboard"):
        metrics_js = os.path.join(content, "dashboard", "data", "metrics.js")
        env = dict(os.environ)
        env["DASHBOARD_SESSIONS"] = np_toggle.param("evaluator.dashboard_sessions", "50")
        env["DASHBOARD_DAYS"] = np_toggle.param("evaluator.dashboard_days", "14")
        env["DASHBOARD_MIN_TOOL_CALLS"] = np_toggle.param("evaluator.min_tool_calls", "1")
        env["WIKI_NAV"] = np_toggle.param("evaluator.wiki_nav", "on")
        env["WIKI_MERMAID"] = np_toggle.param("evaluator.wiki_mermaid", "on")
        env["NP_CONTENT_DIR"] = content
        env["NP_LESSONS_DIR"] = os.path.join(content, "memory", "lessons")
        env["NP_RESOLVED_SUGGESTIONS"] = resolved
        try:
            subprocess.run(
                [sys.executable, os.path.join(_ENGINE, "dashboard", "build.py"), metrics, metrics_js],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except OSError:
            pass

    if no_commit:
        return "no-op"

    if not np_content.content_is_explicit():
        return "skipped: implicit content dir fallback"

    source = "dashboard/data/metrics.jsonl"
    paths = [source, "dashboard/data/metrics.js"]
    try:
        # Gate on the SOURCE OF TRUTH only. metrics.js is a derived artifact that
        # build.py regenerates every run, embedding resolved_last_24h -- a rolling
        # count that changes on its own as seen-markers age out. Diffing it too
        # made every run look dirty and commit "0 record(s)" (#202). It still
        # rides along in the commit; it just never triggers one.
        # Checked with `status`, not `add`+`diff --cached`: staging on the way to
        # deciding NOT to commit leaves files in a shared index for the next
        # writer to sweep up (AGENTS.md "concurrent session").
        st = subprocess.run(["git", "-C", content, "status", "--porcelain", "--", source],
                            capture_output=True, text=True)
        if st.returncode != 0 or not (st.stdout or "").strip():
            return "no-op: no metrics change to commit"
        subprocess.run(["git", "-C", content, "add"] + paths,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        msg = "evaluator(metrics): daily batch (%s) — %d record(s)" % (
            time.strftime("%Y-%m-%d", time.gmtime()), n)
        commit = subprocess.run(["git", "-C", content, "commit", "-q", "-m", msg, "--"] + paths,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if commit.returncode == 0:
            subprocess.run(["git", "-C", content, "push", "-q", "origin", "HEAD:main"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass
    return "aggregated"


if __name__ == "__main__":
    print(aggregate())
