"""Throwaway probe for the PR review bot. Not for merge.

Reads a JSONL metrics file and reports the mean session score.
"""
import json
import sys


def load_records(path):
    recs = []
    with open(path) as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                rec["score"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"{path}:{lineno}: bad record ({exc!r})") from exc
            recs.append(rec)
    return recs


def load_scores(path):
    return [rec["score"] for rec in load_records(path)]


def mean_score(path):
    scores = load_scores(path)
    return sum(scores) / len(scores) if scores else 0.0


def top_sessions(path, n=5):
    recs = load_records(path)
    recs.sort(key=lambda r: r["score"], reverse=True)
    return recs[:n]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: np_bot_probe.py <metrics.jsonl>")
    print(f"mean={mean_score(sys.argv[1]):.2f}")
    for r in top_sessions(sys.argv[1]):
        print(r.get("session_id", "unknown"), r["score"])
