---
name: np-kb-parsing-exported-markdown
description: Gotchas when parsing/ingesting Markdown that was EXPORTED from a rich editor (Google Docs, Confluence, Notion, Word→MD) rather than hand-written. Chiefly: the exporter backslash-escapes Markdown special chars, so a regex that matches before unescaping silently truncates names and collapses distinct entities. Use when writing a parser or ingestion adapter over human-authored `.md` docs (data-model docs, wiki exports, spec dumps) — especially if some tables/sections come out empty or duplicated.
---

# Parsing exported Markdown (Google Docs / rich-editor exports)

Human-authored docs pulled from a rich editor are NOT clean Markdown. Before you
regex over them, account for how the exporter mangles the text — otherwise the
parser fails *silently* (empty/merged records, not an error).

## The big one: backslash-escaped special chars

Google Docs (and similar) export a literal underscore as `\_`, and escape other
Markdown metacharacters too: `\_ \* \. \- \( \) \[ \] \# \` \~ \| \{ \}`. So a
heading that reads `tbl_v3_financial_billingPref` in the doc arrives as:

```
## <a id="_x"></a>tbl\_v3\_financial\_billingPref
```

A name regex like `[A-Za-z0-9_]+` stops dead at the `\`. Two failure modes, both
silent:

1. **Truncation → entity collapse.** `tblstaff\_application` matches only
   `tblstaff`. `tblstaff`, `tblstaff_application`, `tblstaff_season` all reduce to
   one name and MERGE into a single node — distinct records vanish. (Real case:
   178 apparent tables hid 245; ~67 were being merged away.)
2. **Empty records.** `__Column: staff\_id__` won't match `__Column: (\w+)__`, so
   a well-documented table parses with zero columns and looks "undocumented."

**Fix: unescape each line before matching**, at the very top of the parse loop:

```python
_ESCAPE_RE = re.compile(r"\\([^0-9A-Za-z\s])")   # drop the backslash before any escaped punct
for raw in lines:
    line = _ESCAPE_RE.sub(r"\1", raw)
    ...
```

Only strip the backslash before a *non-alphanumeric, non-space* char (real
Markdown escaping); never touch `\n`, `\t`, or a legit `\word`.

## Other rich-export gotchas

- **`<a id="...">` anchor tags** precede real heading text (`## <a id="_x"></a>Name`).
  Strip them before reading the name.
- **Heterogeneous column formats in one corpus.** Some sections use bullets
  (`- __col__`), others a Markdown table (`| Column | Description |`). Handle both;
  when reading a table, skip the header row and the `|---|` separator, and strip
  `[brackets]`/backticks from cell values.
- **Prose masquerading as records.** Single capitalized words ("Notes", "Season")
  and ALL-CAPS lines get mis-captured as entities. Tighten the name regex to a
  known prefix or multi-word PascalCase, not "any Capitalized word."
- **Genuinely empty stubs exist too.** After fixing the above, remaining empties
  may be real: bare `## Name` headings or "Details TBD." in the source. Verify
  against the doc before blaming the parser — and don't backfill from a lossy
  source; get columns from the authoritative system (e.g. live DB introspection).

## Discipline

Parser failures here are silent (Rule 8, [[np-kb-coding-rules]] — treat silent
failures as work). When a doc-sourced record looks wrong, **diff the parser
output against the raw doc bytes** rather than trusting either. Add a regression
test seeded with the *escaped* input, not clean Markdown. For source-to-sink
correctness when the parsed text later hits a query/template, see
[[np-kb-security-review]].
