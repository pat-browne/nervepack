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
import datetime
import json
import os
import subprocess
import sys
import time

import np_content
import np_toggle

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
    home = os.environ.get("HOME") or os.path.expanduser("~")
    inbox = os.environ.get("EVAL_INBOX") or os.path.join(home, ".cache", "nervepack", "evaluator-inbox")
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
        env["DASHBOARD_SESSIONS"] = np_toggle.param("evaluator.dashboard_sessions", "5")
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

    paths = ["dashboard/data/metrics.jsonl", "dashboard/data/metrics.js"]
    try:
        subprocess.run(["git", "-C", content, "add"] + paths,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        diff = subprocess.run(["git", "-C", content, "diff", "--cached", "--quiet", "--"] + paths)
        if diff.returncode == 0:
            return "no-op: no metrics change to commit"
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
