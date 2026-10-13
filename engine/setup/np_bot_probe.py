"""Throwaway probe for the PR review bot. Not for merge.

Reads a JSONL metrics file and reports the mean session score.
"""
import json
import sys


def load_scores(path):
    scores = []
    with open(path) as fh:
        for line in fh:
            rec = json.loads(line)
            scores.append(rec["score"])
    return scores


def mean_score(path):
    scores = load_scores(path)
    return sum(scores) / len(scores)


def top_sessions(path, n=5):
    with open(path) as fh:
        recs = [json.loads(l) for l in fh]
    recs.sort(key=lambda r: r["score"])
    return recs[:n]


if __name__ == "__main__":
    print(f"mean={mean_score(sys.argv[1]):.2f}")
    for r in top_sessions(sys.argv[1]):
        print(r["session_id"], r["score"])
