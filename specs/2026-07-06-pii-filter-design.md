# PII Filter — Design Spec

**Date:** 2026-07-06  
**Status:** Approved — ready for implementation plan  
**Toggle:** `pii_filter` (new, default off)  
**Related:** `wiki/topics/llm-pii-anonymization/` (research basis)

---

## Problem

Nervepack injects content from episodic memory, lessons, and skills into the LLM
context window at every session. That content is derived from real session
transcripts and may contain PII (names, emails, IP addresses, phone numbers,
file paths). The existing `episodic-scrub.sh` / `np_scrub.py` pipeline already
strips secrets/tokens unconditionally, but does not cover PII.

This feature adds a `pii_filter` toggle that — when enabled — scrubs PII from
nervepack content both before it is stored (storage-time, thorough) and before
it is injected into the LLM context window (injection-time, fast).

---

## Scope

**In scope:**
- New `np-pii-filter.py` script (regex layer + optional Presidio NER layer)
- Storage-time filtering: extend `episodic-scrub.sh` to call the filter after
  existing secret scrubbing
- Injection-time filtering: extend `episodic-recall.sh` and `lesson-recall.sh`
  to pipe assembled context through the filter before emitting `additionalContext`
- New `pii_filter` toggle in `toggles.conf`
- Optional setup script `25-install-pii-deps.sh` (Presidio + spaCy)
- Unit + integration tests

**Out of scope:**
- Retroactive re-scrub of episodic files written before the toggle was enabled
  (one-shot migration; add to ROADMAP.md)
- NER at injection time (hook latency constraint; future: daemon approach)
- Round-trip de-anonymization (no Vault; typed placeholders only)
- Filtering skill SKILL.md bodies or wiki content (manually authored, low PII risk)
- Filtering `nervepack-session-directive.sh` (static, no user-generated content)

---

## Key Decisions

| Decision | Choice | Reason |
|---|---|---|
| NER at storage vs injection | Storage only | Injection is on the UserPromptSubmit critical path; NER model cold-start (~500ms) would block the session |
| Regex at injection | Yes | Fast (~0ms), no model load, catches structural PII (email, IP, path, token) |
| Replacement style | Typed placeholders | `[EMAIL]`, `[PERSON]`, etc. — LLM retains enough signal to reason coherently |
| Presidio dependency | Optional | Fail-open: if not installed, full mode falls back to regex-only with a stderr warning |
| Relation to `np_scrub.py` | Additive | `np_scrub.py` already catches secrets/tokens unconditionally. `np-pii-filter.py` adds PII coverage (emails, names, IPs, paths) on top — it runs *after* the existing scrub, not instead of it |
| Toggle default | Off | PII filtering is a behavior change with utility tradeoffs; opt-in |

---

## Architecture

```
INJECTION PATH  (fast mode · regex only · on the critical path)

UserPromptSubmit
  → episodic-recall.sh
      reads memory/episodic/*.md
      assembles ctx string
      pii_filter on? → pipe ctx | np-pii-filter.py --mode fast
      emit additionalContext
  → lesson-recall.sh        (same shape)


STORAGE PATH  (full mode · regex + NER · async, latency-free)

SessionEnd / PreCompact
  → episodic-capture.sh generates summary
  → episodic-scrub.sh  ←── already runs (secrets/tokens, unconditional)
  → pii_filter on? → pipe | np-pii-filter.py --mode full
  → commit to memory/episodic/<topic>.md
```

---

## Components

### 1. `engine/setup/np-pii-filter.py` *(new)*

Stdin → stdout filter. Typed placeholder replacements.

**CLI:** `np-pii-filter.py --mode fast|full`

**Regex rules (both modes):**

| Rule | Pattern shape | Placeholder |
|---|---|---|
| Email | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | `[EMAIL]` |
| Phone (US) | `(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}` | `[PHONE]` |
| SSN | `\d{3}-\d{2}-\d{4}` | `[SSN]` |
| Private IP | RFC1918: 10.x, 172.16-31.x, 192.168.x | `[IP]` |
| Unix path w/ username | `/home/[a-z_][a-z0-9_-]*/`, `/Users/[A-Za-z][A-Za-z0-9_-]*/` | `[PATH]` |
| API tokens | Reuse patterns from `np_scrub.py` (sk-, gh-, AKIA, Bearer, etc.) | `[TOKEN]` |

Note: `np_scrub.py` already catches tokens at storage time with `[REDACTED-SECRET]`.
The `[TOKEN]` rule in np-pii-filter covers the injection-time path where
np_scrub.py has not yet run (or where old content predates the toggle).

**NER rules (full mode only — requires Presidio):**

| Entity | Presidio type | Placeholder |
|---|---|---|
| Person name | `PERSON` | `[PERSON]` |
| Organisation | `ORGANIZATION` | `[ORG]` |
| Location | `LOCATION` | `[LOCATION]` |
| Phone (NER) | `PHONE_NUMBER` | `[PHONE]` |
| Email (NER) | `EMAIL_ADDRESS` | `[EMAIL]` |
| SSN (NER) | `US_SSN` | `[SSN]` |

NER runs after regex; already-substituted placeholders are not double-processed.

**Behaviour contract:**
- Always exits 0 (fail-open)
- Any exception → pass input through unchanged, log to stderr
- Missing Presidio in full mode → stderr: `[np-pii] presidio unavailable, regex-only`, proceed
- Operates on UTF-8 text; invalid bytes passed through unchanged

---

### 2. `engine/setup/episodic-scrub.sh` *(modified)*

After the existing `sed -E` rules (which run unconditionally), add:

```bash
if np_enabled pii_filter 2>/dev/null; then
  content="$(printf '%s' "$content" | "$HERE/np-pii-filter.py" --mode full)"
fi
```

Same pattern for `np_scrub.py` (used on bash-free hosts via MCP capture):
add a second pass of PII regex rules (matching the fast-mode rules in
`np-pii-filter.py`) gated by `os.environ.get("NP_PII_FILTER") == "1"`.
The MCP server (`np-mcp-server.py`) sets this env var when it calls `scrub()`
if it detects the `pii_filter` toggle is on (via `np_enabled` shell-out or a
cached toggle read). NER is not applied on the MCP path (no Presidio in that
context).

---

### 3. `engine/setup/episodic-recall.sh` *(modified)*

After the `ctx` string is assembled, before the `jq` output:

```bash
if np_enabled pii_filter 2>/dev/null; then
  ctx="$(printf '%s' "$ctx" | "$HERE/np-pii-filter.py" --mode fast)"
fi
```

---

### 4. `engine/setup/lesson-recall.sh` *(modified)*

Same three-line addition as episodic-recall.sh, after `ctx` is assembled.

---

### 5. `engine/setup/toggles.conf` *(modified)*

Add after the `memory` line:

```
pii_filter|shared|runtime|off|
```

---

### 6. `engine/setup/25-install-pii-deps.sh` *(new, optional)*

```bash
#!/usr/bin/env bash
# Optional: install Presidio + spaCy for np-pii-filter --mode full.
# Safe to skip — filter degrades gracefully to regex-only without these.
pip install presidio-analyzer presidio-anonymizer
python -m spacy download en_core_web_lg
```

Numbered 25 (runs after Python baseline `20-`, before hooks `50-`). Idempotent.
Failing silently is acceptable.

Doctor check: add `pii_filter_full` capability to `np-doctor.sh` — reports
whether `import presidio_analyzer` succeeds.

---

### 7. `ARCHITECTURE.md` *(modified)*

Add one row to the Feature catalog table:

```
| **PII filter** (context-window and storage-time scrub) | `pii_filter` (default off) |
  `np-pii-filter.py`, `episodic-scrub.sh` (extended), `episodic-recall.sh` (extended),
  `lesson-recall.sh` (extended), `25-install-pii-deps.sh` |
  `specs/2026-07-06-pii-filter-design.md` |
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| `np-pii-filter.py` crashes | Pass input through unchanged; exit 0 |
| Presidio not installed, `--mode full` requested | Stderr warning; run regex-only; exit 0 |
| Hook filter subprocess fails | Hook continues with unfiltered `ctx`; session not blocked |
| Invalid UTF-8 input | Pass bytes through unchanged; log to stderr |

---

## Testing

`engine/setup/tests/pii/` (new directory, follows existing test patterns):

**`test_pii_filter.py`** (unit, stdlib):
- Each regex rule fires on a matching input and produces the right placeholder
- Already-substituted placeholders are not double-processed
- `--mode fast` does not invoke NER (mock/assert no Presidio import)
- Graceful degradation: mock missing Presidio → regex-only output, exit 0
- Exception in filter → input passed through unchanged, exit 0

**`test_pii_hooks.sh`** (integration):
- `episodic-recall.sh` with `pii_filter=on`: output contains no raw emails or IPs
- `episodic-recall.sh` with `pii_filter=off`: output identical to unfiltered baseline
- `lesson-recall.sh` same pair

---

## Limitations (document honestly)

- **NER at injection time is not covered.** Names embedded in episodic content
  injected at recall time are only caught if they were scrubbed at storage time
  (i.e., the episodic file was captured *after* `pii_filter` was enabled with
  Presidio available). Content written before the toggle was on retains names
  until retroactively re-scrubbed (out of scope; roadmap).

- **Regex misses names.** The fast-mode regex tier catches structural PII
  (emails, IPs, phones, tokens, paths) but not names, organisations, or
  contextual references like project names or client names in prose.
  Full-mode NER at storage time addresses this for new captures only.

- **Not a compliance guarantee.** The filter is defense-in-depth, not a
  certified PII-free boundary. Contextual and implicit PII (inferences,
  relationships, quasi-identifiers) is out of scope for this implementation.

---

## Roadmap Items (not in this spec)

- One-shot retroactive re-scrub of existing `memory/episodic/*.md` files
- NER daemon warmed at SessionStart for low-latency injection-time NER
- `pii_filter_full` capability surfaced in the dashboard
