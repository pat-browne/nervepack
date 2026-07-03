#!/usr/bin/env python3
"""Emit deterministic `signals` JSON for a session.

    argv[1] = session_id   argv[2] = transcript_path (optional)

Log-authoritative for hook fires; tolerant transcript parse for skills/tool_calls.
Stdlib only — no third-party deps (see CLAUDE.md § "Harness language policy").
Toggle resolution is single-sourced in bash: we shell out to `np_enabled` rather
than reimplement the resolver here. Fail-open: any error degrades a field to its
empty/zero default; the script never raises out to the caller.

This is the proof-of-concept port establishing the bash→Python pattern: the
parsing/data-assembly logic that kept hitting bash's pipefail+grep footguns now
lives in a language with real data structures, while the hot-path glue stays bash.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "np-toggle-lib.sh")
sys.path.insert(0, HERE)
import np_bashlib  # noqa: E402  — bash shell-out works under Git-bash on Windows (no-op off it)


def cmd_fingerprint(cmd):
    """Stable fingerprint of a shell command: whitespace-collapsed, sha256[:16].
    MUST match lesson-guard.sh's fingerprint so a gated command and the same
    command executed in the transcript hash identically."""
    return hashlib.sha256(" ".join(str(cmd).split()).encode("utf-8")).hexdigest()[:16]


def signal_log_path(sid):
    base = os.environ.get(
        "NP_SIGNAL_DIR", os.path.expanduser("~/.cache/nervepack/session-signals")
    )
    return os.path.join(base, sid.replace("/", "_") + ".log")


def count_markers(log_path):
    """Count fire markers by prefix. Missing file -> all zero (fail-open).
    Returns (lesson_guard, lesson_recall, episodic_recall).
    lesson-recall REPLACES the old playbook-recall/strategy-recall markers —
    those hooks were merged into engine/setup/lesson-recall.sh and no longer
    exist, so their branches are gone rather than kept dead alongside this."""
    pg = lr = er = 0
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("lesson-guard"):
                    pg += 1
                elif line.startswith("lesson-recall"):
                    lr += 1
                elif line.startswith("episodic-recall"):
                    er += 1
    except OSError:
        pass
    return pg, lr, er


def gated_fingerprints(log_path):
    """Fingerprints of commands a lesson guard fired on, parsed from the
    `lesson-guard <gate> <topic> :: <fp>` markers. Old markers without `:: fp`
    contribute nothing (backward-compatible). Missing file -> empty (fail-open)."""
    fps = set()
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("lesson-guard"):
                    continue
                _, sep, rest = line.partition(" :: ")
                if sep:
                    fps.add(rest.strip())
    except OSError:
        pass
    return fps


def episodic_struggles(sid):
    """Count this session's struggles[] from the episodic inbox. The real struggle
    data is produced by the episodic capture pass (which runs before the evaluator,
    both live and in the back-capture sweep), not the transcript or signal log — so
    read it across-pipeline, matched by session_id. Take the max across duplicate
    captures (PreCompact checkpoint + session-end). Fail-open 0."""
    base = os.environ.get(
        "EPISODIC_INBOX", os.path.expanduser("~/.cache/nervepack/episodic-inbox")
    )
    best = 0
    try:
        for name in os.listdir(base):
            if not name.endswith(".jsonl"):
                continue
            with open(os.path.join(base, name), encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if sid not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("session_id") == sid:
                        st = rec.get("struggles")
                        if isinstance(st, list):
                            best = max(best, len(st))
    except OSError:
        pass
    return best


def directive_tokens():
    """Rough fixed-cost (tokens) of nervepack's own SessionStart context injection —
    the directive .md, ~4 chars/token. Lets the dashboard attribute nervepack's own
    overhead (Manus: measure your injected-context cost). Fail-open 0."""
    md = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "nervepack-session-directive.md")
    try:
        with open(md, encoding="utf-8", errors="replace") as fh:
            return len(fh.read()) // 4
    except OSError:
        return 0


def _tokens(acc):
    """Finalize the token accumulator into the emitted shape (+ total)."""
    t = {k: acc[k] for k in ("input", "output", "cache_read", "cache_creation")}
    t["total"] = sum(t.values())
    return t


def parse_transcript(path):
    """Best-effort single pass: tool_use count, skills, token usage, and the
    fingerprints of executed Bash commands (for the playbook-heeded heuristic).

    Token usage is summed ONCE per unique assistant `message.id` — Claude Code logs
    one JSONL line per content block of a turn, all sharing the same id and the same
    usage object, so summing every line triple-counts (cache_read inflates to
    millions). Dedup by id is the deterministic fix. Messages without a usage block
    or id are skipped (undercount-safe beats double-count)."""
    tool_calls = 0
    skills = set()
    seen = set()
    exec_fps = set()
    acc = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    if not path or not os.path.isfile(path):
        return 0, [], _tokens(acc), exec_fps
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                skills.update(re.findall(r'"skill":"([^"]+)"', line))
                obj = None
                if '"tool_use"' in line:
                    tool_calls += 1
                    if '"Bash"' in line:
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            obj = None
                        content = ((obj or {}).get("message") or {}).get("content")
                        if isinstance(content, list):
                            for b in content:
                                if (isinstance(b, dict) and b.get("type") == "tool_use"
                                        and b.get("name") == "Bash"):
                                    c = (b.get("input") or {}).get("command")
                                    if c:
                                        exec_fps.add(cmd_fingerprint(c))
                if '"usage"' not in line:
                    continue
                if obj is None:
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                msg = obj.get("message") or {}
                usage, mid = msg.get("usage"), msg.get("id")
                if not usage or not mid or mid in seen:
                    continue
                seen.add(mid)
                acc["input"] += usage.get("input_tokens") or 0
                acc["output"] += usage.get("output_tokens") or 0
                acc["cache_read"] += usage.get("cache_read_input_tokens") or 0
                acc["cache_creation"] += usage.get("cache_creation_input_tokens") or 0
    except OSError:
        return 0, [], _tokens(acc), exec_fps
    return tool_calls, sorted(skills), _tokens(acc), exec_fps


def directive_present():
    """Mirror `np_enabled directive` (fail-open: on/True if the check errors)."""
    try:
        rc = subprocess.run(
            np_bashlib.argv(["bash", "-c", 'source "$1"; np_enabled directive', "_", LIB]),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        return rc == 0
    except Exception:
        return True


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    transcript = sys.argv[2] if len(sys.argv) > 2 else ""

    log_path = signal_log_path(sid)
    pg, lr, er = count_markers(log_path)
    tool_calls, skills, tokens, exec_fps = parse_transcript(transcript)
    # heeded = guarded commands the session did NOT then run (intervention worked).
    heeded = len(gated_fingerprints(log_path) - exec_fps)

    record = {
        "skills_invoked": skills,
        "playbook_fires": pg,
        "playbook_heeded": heeded,
        "recall_injections": lr + er,
        "directive_present": directive_present(),
        "directive_tokens": directive_tokens(),
        "struggles": episodic_struggles(sid),
        "tool_calls": tool_calls,
        "tokens": tokens,
    }
    print(json.dumps(record, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: never disrupt the SessionEnd judge. Empty stdout -> caller
        # (np-evaluator.sh) falls back to '{}'.
        pass
