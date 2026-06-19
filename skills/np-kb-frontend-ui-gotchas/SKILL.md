---
name: np-kb-frontend-ui-gotchas
description: Framework-level UI implementation gotchas (Preact/React and similar) that bite repeatedly — focusing/selecting dynamically-mounted inputs, making inline-edit commit exactly once, and silencing ResizeObserver loop warnings. Use when building editable/inline-rename fields, doing focus management, wiring a ResizeObserver, or debugging "the input won't focus", "typing doesn't replace the text", "it saved twice / didn't save", or "ResizeObserver loop completed with undelivered notifications", or a CSS bar/progress "fill" that renders invisibly because an inline element ignores width/height.
---

# Frontend UI gotchas

Reusable, framework-level traps hit while building real UI. Apply in any
Preact/React UI — websites, browser extensions, future apps.

## 1. `autofocus` is a no-op on dynamically-mounted inputs (Preact)

The HTML `autofocus` attribute is only honored while the browser **parses the
initial page**. An input you mount *later* (open a rename field, add a row,
show a modal) will **not** auto-focus from `autofocus`.

- **React** special-cases the `autoFocus` prop — it calls `.focus()` on mount, so
  it "works." **Preact does not** — it just sets the attribute, which does nothing
  post-load. Don't assume parity.
- Symptom: the field looks editable but isn't focused, so **typing doesn't go in
  / doesn't replace the text**, and because it never had focus, **blur never
  fires to save**. (Exactly the meeting-template rename bug — twice.)

**Fix — focus + select via a ref on mount, guarded against re-select while typing:**

```tsx
const focusPending = useRef(false)
// when entering edit mode: focusPending.current = true; setEditingId(id)

<input
  defaultValue={name}
  ref={(el) => {
    if (el && focusPending.current) {   // guard: only on the mount that opened edit
      focusPending.current = false      // ...not on every typing re-render (would clobber input)
      el.focus()
      el.select()                       // select-all so the first keystroke replaces
    }
  }}
/>
```

A plain inline `ref` runs on every render — the `focusPending` flag is what keeps
it to the one mount that opened the field. A `useEffect` keyed on the editing id
works too.

## 2. Inline-edit commit fires twice (Enter, then blur) — make it commit once

Pressing Enter typically runs your keydown handler *and* then blurs the field
(focus moves / element unmounts), so a naive "commit on Enter" + "commit on blur"
fires **twice**. With persistence on commit, that's a double write.

**Fix — funnel every commit path through one guarded function:**

```tsx
const committed = useRef(false)
function beginEdit(id) { committed.current = false; focusPending.current = true; setEditingId(id) }
function commit(id, value) {
  if (committed.current) return
  committed.current = true
  onRename(id, value)
  setEditingId(null)
}
// onKeyDown: Enter OR Tab -> commit(...);  Escape -> cancel (setEditingId(null))
// onBlur: commit(...)   // click-away / Tab-out saves, even if unchanged
```

Commit on **Enter, Tab, and blur** (so click-away and tab-out both save, including
the unchanged default value); cancel on Escape. Reset the `committed` flag in
`beginEdit` so the next edit session can commit again.

## Testing (lock these so they don't regress)

These broke twice in one project — guard them with tests that assert the
*behavior*, not the attribute:
- Entering edit mode focuses the input (`document.activeElement === input`) **and**
  selects its text (`selectionStart === 0 && selectionEnd === value.length`) with
  no manual focus event.
- Commit fires on Tab and on blur (incl. unchanged), and **exactly once** on Enter
  (`toHaveBeenCalledTimes(1)` — not just `toHaveBeenCalledWith`).

## 3. `ResizeObserver loop completed with undelivered notifications`

A `ResizeObserver` whose callback **synchronously sets state** (or otherwise
mutates layout) re-lays-out the observed element and re-triggers the observer in
the same frame. Chrome surfaces this as the warning above — harmless, but it
spams the console and shows up in error overlays / monitoring.

**Fix: defer the work out of the observer callback with `requestAnimationFrame`,
and cancel the pending frame on cleanup:**

```ts
let raf = 0
const check = () => setState(el.scrollWidth > el.clientWidth + 1)
check() // initial read — synchronous is fine, it's not inside the observer
const ro = new ResizeObserver(() => {
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(check)
})
ro.observe(el)
return () => { cancelAnimationFrame(raf); ro.disconnect() }
```

The rAF also debounces bursts of resize callbacks into one state update. (From
the meeting-template tab-overflow detector.)

## 4. A progress-bar / chart "fill" as an inline `<span>` renders invisibly (CSS)

`width` and `height` **do not apply to inline boxes**. So a bar built as
`<span class="track"><span class="fill"></span></span>` where `.fill` is a plain
`<span>` collapses to zero size — the track shows, but the coloured fill never
appears, no matter what `width:X%` / `height:100%` you set on it.

- Symptom: progress/score/usage bars where the background track is visible but the
  fill is blank — looks like "the data isn't binding," but it's pure CSS. (Hit on
  the nervepack P2 dashboard's asset-usefulness bars — the bug was baked into the
  page's first draft.)

**Fix — make the fill a block (or the track a flex container):**

```css
.bar .fill { display: block; height: 100%; background: var(--viz-line); }
/* width:X% set inline per bar */
```

`display:inline-block` also works; the point is just to get it out of inline flow
so width/height take effect. Same trap applies to any inline element you try to
size — `<a>`, `<span>`, `<em>`. When an element "ignores" its width/height, check
its `display` first.

## 5. Hover dots/tooltips on a `preserveAspectRatio="none"` SVG line chart

A full-width SVG line chart commonly stretches with `viewBox="0 0 1000 120"` +
`preserveAspectRatio="none"` and a CSS-fixed height. The trap: that stretch is
**x-only** (the viewBox width 1000 → the rendered pixel width; the height maps
120 → its fixed 120px, so **vertical viewBox units == pixels**). Two consequences:

- **Don't put markers as SVG `<circle>`** — non-uniform x-scaling squashes them into
  ellipses, and their hit area stretches too. Render dots as **HTML elements
  positioned with `left: <x/1000*100>%`** (resize-proof, no JS) and `top` in px
  (since y is 1:1). The polyline still uses viewBox coords.
- **Drive hover in pixel space, not SVG coords.** On `mousemove`, read the wrapper's
  `getBoundingClientRect()`, map `clientX → nearest index` (`round((x-rect.left)/
  rect.width*(n-1))`), then place an HTML tooltip + highlight dot from that index's
  precomputed coords. Mixing SVG user-units and screen pixels is the usual source of
  "the tooltip is offset / drifts on resize."
- **Scale honestly, but don't let real data read as "missing."** A *fixed* 0–N scale is
  correct for a bounded metric (a 0–100 score) — don't auto-scale it, or a 9/100 looks
  full. But a flat low line hugging the axis reads as *no data*; surface each point (HTML
  dot per above) so it's clearly "present but low." For values spanning **orders of
  magnitude** (token counts), a linear scale crushes everything under one outlier into a
  ~1px sliver — use a **log scale**: `log10(max(v,1)) / log10(max(max,10))` (floor the
  denominator ≥10 and `max(v,1)` so v=0 → baseline, never `NaN`/`-Infinity`). Guard the
  degenerate min==max / single-point cases too — any `NaN` coord makes the SVG draw
  nothing. (Both hit the nervepack P2 dashboard's trend + token charts, 2026-06-18.)

Verify by serving the page (Playwright blocks `file://`) and dispatching a synthetic
`mousemove` — assert the tooltip becomes visible and exactly one dot is highlighted.
(From the nervepack dashboard's chart-hover work; the chart code lives in
`dashboard/index.html`.)
