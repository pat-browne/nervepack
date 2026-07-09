#!/usr/bin/env python3
"""Extract readable conversation text from a Claude Code transcript JSONL.

Skips image/attachment (base64) blocks, joins text + tool_use + tool_result, and
emits the LAST `cap_bytes` of clean UTF-8 to stdout. Runs OFF the hot path
(SessionEnd / PreCompact / cron), so per nervepack's harness language policy the
heavy parsing lives here in Python instead of an inline jq monster duplicated
across episodic-capture.sh and np-evaluator.sh. One tested extractor, one cap knob.

Usage:  np-transcript-extract.py <transcript.jsonl> [cap_bytes]
Fail-open: any read/parse error -> empty stdout, exit 0 (the caller bails cleanly).
"""
import sys
import json
import re

# Collapse pathological long base64/hex runs (a cat'd binary, a data: URI, an
# embedded blob inside a tool_result TEXT block — which §6's image-block skip does
# NOT catch). No legitimate prose/identifier is anywhere near 500 unbroken
# base64-alphabet chars, so this only strips genuine binary noise — directly
# serving the "limit raw input" goal before the byte cap is even applied.
_BLOB = re.compile(r"[A-Za-z0-9+/=_-]{500,}")


def _scrub_blobs(text):
    return _BLOB.sub("[binary/base64 omitted]", text)


def extract(path):
    """Return the full readable conversation text for a transcript JSONL."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # tolerate a stray non-JSON line
            content = (obj.get("message") or {}).get("content")
            if content is None:
                continue
            if isinstance(content, str):
                out.append(content)
            elif isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    t = blk.get("type")
                    if t == "text":
                        out.append(blk.get("text", ""))
                    elif t == "tool_use":
                        out.append("[tool_use: " + (blk.get("name") or "?") + "]")
                    elif t == "tool_result":
                        c = blk.get("content")
                        if isinstance(c, str):
                            out.append(c)
                        elif isinstance(c, list):
                            out.append("\n".join(
                                b.get("text", "") for b in c
                                if isinstance(b, dict) and b.get("type") == "text"
                            ))
                        else:
                            out.append("[tool_result]")
                    # image / other blocks are intentionally dropped — never let
                    # base64 attachment bytes reach the summarizer's stdin.
    return _scrub_blobs("\n".join(out))


def last_user_text(path):
    """Return the LAST genuine (human-typed) user text message in a transcript.

    Many synthetic turns also arrive as `type:"user"` lines: `tool_result`
    blocks, hook `additionalContext` injections, `<task-notification>`
    background-task completions, session-continuation banners, slash-command
    envelopes, and SDK-injected prompts. These MUST NOT be returned as "the
    user's instruction" — doing so poisons the resume pointer.

    Discrimination is an ALLOWLIST on the field Claude Code stamps on genuine
    keyboard input: a line qualifies only if `obj["type"] == "user"` AND
    `obj["promptSource"] == "typed"`. Every synthetic category above lacks that
    (the field is absent, or `system`/`queued`/`sdk`/`suggestion_accepted`), so
    the allowlist fails SAFE — if a message isn't clearly typed we skip it, and
    an empty last-instruction is fine (the pointer still carries branch + SDD
    ledger) versus returning a task-notification as if it were user intent.

    A content-shape check is kept as a defensive secondary guard: content must
    be a plain str or a list whose blocks are ALL `type=="text"` (any
    `tool_result`/non-text block disqualifies the line). Recency wins: the last
    qualifying line found is returned.
    """
    last = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # tolerate a stray non-JSON line
            if obj.get("type") != "user" or obj.get("promptSource") != "typed":
                continue
            content = (obj.get("message") or {}).get("content")
            if isinstance(content, str):
                last = content
            elif isinstance(content, list) and content:
                texts = []
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "text":
                        texts = None
                        break
                    texts.append(blk.get("text", ""))
                if texts is not None:
                    last = "\n".join(texts)
    return _scrub_blobs(last) if last is not None else ""


def main(argv):
    if len(argv) < 2:
        return 1
    if argv[1] == "--last-user":
        if len(argv) < 3:
            return 1
        try:
            text = last_user_text(argv[2])
        except OSError:
            return 0  # fail-open: caller's bail-on-empty handles it
        data = text.encode("utf-8", "replace")
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            pass  # downstream closed early — not an error
        return 0
    path = argv[1]
    try:
        cap = int(argv[2]) if len(argv) > 2 else 200000
    except ValueError:
        cap = 200000
    try:
        text = extract(path)
    except OSError:
        return 0  # fail-open: caller's `[[ -n "$convo" ]]`/bail handles emptiness
    data = text.encode("utf-8", "replace")
    if cap > 0 and len(data) > cap:
        data = data[-cap:]  # recency: the tail is "where we left off"
    try:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        pass  # downstream closed early (e.g. `| head`) — not an error
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
