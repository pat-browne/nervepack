#!/usr/bin/env python3
"""nervepack 'local' LLM backend — drives an OpenAI-compatible /chat/completions endpoint
(Ollama /v1, Open WebUI, LM Studio, vLLM, ...). Called by np-llm.sh's `local` backend.

Usage: np-llm-local.py complete [--system S]   (prompt on stdin -> text on stdout)
Env: NP_LLM_BASE_URL (full base incl. version path), NP_LLM_API_KEY (optional),
     NP_LLM_MODEL_CHEAP (model name), NP_LLM_TIMEOUT (seconds, default 120).
Exit 0 on success; nonzero (+ one-line stderr) on any error.
"""
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = float(os.environ.get("NP_LLM_TIMEOUT", "120"))


def main(argv):
    if (argv[1:2] or [""])[0] != "complete":
        print(f"np-llm-local: only 'complete' mode supported, got '{argv[1:2]}'", file=sys.stderr)
        return 2
    system = None
    if "--system" in argv:
        i = argv.index("--system")
        system = argv[i + 1] if i + 1 < len(argv) else None

    base = os.environ.get("NP_LLM_BASE_URL", "").rstrip("/")
    model = os.environ.get("NP_LLM_MODEL_CHEAP", "")
    if not base:
        print("np-llm-local: NP_LLM_BASE_URL is required", file=sys.stderr); return 2
    if not model:
        print("np-llm-local: NP_LLM_MODEL_CHEAP is required", file=sys.stderr); return 2

    prompt = sys.stdin.read()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": model, "messages": messages, "stream": False}).encode()

    req = urllib.request.Request(base + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    key = os.environ.get("NP_LLM_API_KEY")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"np-llm-local: HTTP {e.code} from {base}", file=sys.stderr); return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"np-llm-local: cannot reach {base}: {e}", file=sys.stderr); return 1
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print("np-llm-local: unexpected response shape", file=sys.stderr); return 1

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
