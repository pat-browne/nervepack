# Ingest protocol — adding a source to `sources/`

When `np-core-contribute` step 3 routes a contribution to `sources/<topic>/`,
do not silently write the file. Run this suggest-and-prompt flow
(mirrors CLAUDE.md § "Wiki layer / Ingest protocol").

## Steps

1. **Validate the curation rule** — confirm all of:
   - Official technical reference? (spec, RFC, PEP, official tutorial)
   - Has source URL + version + scope?
   - Trimmed to consulted sections, not a full mirror?
   - Not a marketing/blog/aggregator/SO answer?
   - Not duplicating `context7` coverage without a durability reason?

2. **Count sources:**
   ```bash
   TOTAL=$(find ~/Code/nervepack/sources -name '*.md' | wc -l)
   PARENT=$(find ~/Code/nervepack/sources/<topic> -name '*.md' 2>/dev/null | wc -l)
   ```

3. **Find least-referenced source** in `<topic>/` — count `[[<source>]]`
   backlinks from `wiki/` and `skills/`; tiebreak by oldest `captured_date`.

4. **Surface counts + three options** via `AskUserQuestion`:
   - **Add** — disabled if `TOTAL ≥ 300` without override
   - **Rotate** — archive least-referenced first, then add (recommended if `TOTAL ≥ 100`)
   - **Skip** (Other: …)

5. **After the user chooses:** write the file with full frontmatter
   (see CLAUDE.md § "Source frontmatter"), append a `log.md` entry, and
   update the relevant `wiki/entities/<topic>.md` synthesis page to link
   the new source.

6. **Commit** as `source(<topic>): add <name>`.
