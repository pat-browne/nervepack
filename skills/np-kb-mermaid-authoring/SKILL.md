---
name: np-kb-mermaid-authoring
description: Gotchas for authoring portable Mermaid diagrams that render correctly on GitHub and in editor/VSCode previews — not just in an online validator. Use when writing or embedding a Mermaid diagram in Markdown, or debugging one that renders as raw text, shows literal `&entity;` codes in labels, or fails to draw on GitHub/VSCode even though mermaid.live says it's valid.
---

# Authoring portable Mermaid diagrams

Mermaid runs in several engines that do **not** agree: the online validators
(mermaid.live, Mermaid Chart — lenient, decode-happy), GitHub's renderer, and the
editor preview (`bierner.markdown-mermaid` in VSCode). A diagram that validates
online can still render broken on GitHub/VSCode. Author for the strict targets.

## Gotchas

### 1. No HTML entities in node/edge labels — use plain Unicode
`&middot;`, `&mdash;`, `&amp;`, `&#8617;` inside a label render as **literal text**
(you see `&middot;`) on GitHub and in VSCode previews. The online validators
silently decode them, which *masks* the bug — it looks fine where you test it.

- Bad:  `a["SQL Server &middot; cmoltp"]`
- Good: `a["SQL Server · cmoltp"]`  ← paste the real Unicode char (`·` `—` `→` `&`)

`<br/>` for line breaks **is** supported across engines — that one's fine.

### 2. Don't style a subgraph via `class` — color the member nodes
A `class SUBGRAPH_ID myClass;` statement (applying a class to a *subgraph id*) is
flaky across mermaid versions and can fail the whole diagram render. Apply the
class to the member **nodes** instead, or use `style SUBGRAPH_ID fill:...`
(more widely supported than `class` on a subgraph).

- Risky: `class SRC_EXT ext;`
- Safe:  `class sfdc,twlo,csapi ext;`

### 3. Verify against the real target, not just an online validator
"Valid in mermaid.live" ≠ "renders right on GitHub." When a diagram is destined
for a GitHub README/doc or a VSCode-previewed file, check it *there*. The
decode-happy validators hide the entity and subgraph-styling bugs above.

## Pre-flight checklist
- **Labels:** plain text + Unicode + `<br/>` only — zero `&...;` entities.
- **Styling:** `classDef`/`class` on **nodes**; avoid `class` on subgraph ids.
- **Special chars** in a label (`(` `)` `:` `/`): wrap the whole label in `"..."`.

## Convert mermaid → editable Excalidraw (headless / batch)

For one-off interactive editing, use the `pomdtr.excalidraw-editor` Insert → Mermaid
GUI. To convert `.mmd` files to `.excalidraw` scenes **programmatically** (e.g. to
commit editable scenes alongside the source), run Excalidraw's own converter in a
headless browser — there is no Node CLI, and mermaid needs a real DOM:

1. Navigate a headless browser to a CSP-free origin (`https://example.com`), not
   `about:blank` (blocks module imports) and not `excalidraw.com` (strict CSP).
2. In-page, dynamic-import from a CDN and convert:
   ```js
   const { parseMermaidToExcalidraw } = await import('https://esm.sh/@excalidraw/mermaid-to-excalidraw@1.1.2');
   const exc = (await import('https://esm.sh/@excalidraw/excalidraw@0.17.6')).default; // GOTCHA: under .default
   const { elements, files } = await parseMermaidToExcalidraw(def);
   const scene = { type:'excalidraw', version:2, source:'mermaid-to-excalidraw',
     elements: exc.convertToExcalidrawElements(elements),   // NOT a top-level export
     appState:{ viewBackgroundColor:'#ffffff', gridSize:null }, files: files||{} };
   ```
3. Write `JSON.stringify(scene)` to a `*.excalidraw` file; open with the editor.

**Gotchas:** `convertToExcalidrawElements` lives on the **`.default`** export of
`@excalidraw/excalidraw` (top-level `exc.convertToExcalidrawElements` is `undefined`).
The importer keeps structure/labels/arrows but **simplifies `classDef` colors and
nested-subgraph layout** — expect to re-style on the canvas.

## Related
- [[np-env-vscode-setup]] — `bierner.markdown-mermaid` (preview mermaid) and
  `pomdtr.excalidraw-editor` (convert mermaid → editable Excalidraw via Insert → Mermaid).
- [[np-kb-intentional-design]] — when the diagram is part of a designed page.
