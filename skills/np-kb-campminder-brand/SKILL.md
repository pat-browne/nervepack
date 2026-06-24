---
name: np-kb-campminder-brand
description: Campminder's internal data-team tool brand — the dark-theme, purple-accent, Manrope token set used by the data-tools portal. Use when building or styling ANY Campminder internal web tool/dashboard (data-tools, data-catalog, MCP UIs) so it matches the team's existing surfaces instead of inventing colors/fonts. This is the COMPANY brand for work tools — distinct from [[np-kb-branding]] (Pat's personal warm-light identity); use this one for Campminder properties.
---

# Campminder brand — internal data-team tools

The visual identity for Campminder's **internal data-team web tools**. New tools
(data-catalog dashboard, MCP UIs, batch portals) should wear these tokens so the
team's surfaces feel like one product. This is the **company/work** brand —
distinct from [[np-kb-branding]], which is Pat's *personal* warm-light identity.
For a Campminder property, default here; for Pat's own sites/extensions, use that.

**Source of truth:** `data-tools` portal —
`~/Code/data-tools/data_portal/templates/base.html` (`:root` block + component
styles). It's vanilla CSS custom properties, no framework. When these tokens
change, update there first, then reconcile this skill.

> Spelling: **Campminder** (capital C, lowercase m) in all UI copy, even though
> the logo file is `cmlogo-white.png` and older code/ADO uses `CampMinder`.

## Canonical tokens (dark theme)

```css
:root {
  /* Foundation — dark */
  --bg-color:      #282828;  /* page background */
  --text-color:    #F0F0F0;  /* primary text */
  --container-bg:  #505050;  /* cards / containers / inputs / result boxes */
  --border-color:  #A0A0A0;  /* borders, dividers, muted text */

  /* Brand accent — purple (NOT green/teal) */
  --primary-color: #773DBD;  /* buttons, links, active states, focus, accents */
  --primary-hover: #380F8C;  /* hover (darker purple) */

  /* Status / semantic */
  --success-color:      #69db7c;
  --status-error-color: #ff6b6b;  /* error boxes (bright, readable on dark) */
  --field-error-color:  #e74c3c;  /* required-field border + badge */
  --warning-color:      #fcc419;
  --info-color:         #b3d0ff;
  --info-border-color:  #3f7fbb;
  --dry-run-bg:     #fff3cd;  /* dry-run banner (the one light surface) */
  --dry-run-border: #f0a500;
  --dry-run-text:   #7d4e00;
}
```

### Typography

```css
--font-body: 'Manrope', sans-serif;   /* Google Fonts, wght 200..800 */
/* base 12px, line-height 1.6; headings 14–15px; footer 11px */
```

Load: `<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@200..800&display=swap" rel="stylesheet">`

### Assets

- Logo (nav, on dark): `data_portal/static/cmlogo-white.png` (render ~32px tall)
- Favicon: `data_portal/static/cm-favicon.ico`
- "Powered by" footer mark: `static/pinky.ico`

## Applying it (the discipline)

The same 60-30-10 scarcity rule from [[np-kb-intentional-design]] holds: the dark
neutrals (`--bg-color`, `--container-bg`, `--text-color`) carry the page; the
**purple accent appears only on actionable / active / selected elements** — never
as a decorative wash. On the dark ground the saturated purple reads as signal.

- **Data-viz / graph surfaces:** dark canvas is a strength — a single purple
  accent on selected/active nodes and edges pops against `#282828`; use
  `--border-color` greys for inactive/dimmed elements and the status hues for
  semantic state. Pair status with a label/icon, never color alone (WCAG 1.4.1).
- **Cards/inputs:** `--container-bg` on `--bg-color`, `--border-color` hairline.
- **Buttons:** primary = solid `--primary-color`, white text, `--primary-hover`
  on hover; secondary = `--container-bg` fill.
- **Focus:** visible ring in `--primary-color`; never `outline:none` bare.

## Caveat — internal-tool brand vs public marketing brand

These tokens are the **internal data-tools** palette, validated as the de-facto
brand for data-team tooling. Campminder's public-facing marketing brand may use
different colors; if a tool is customer-facing, confirm against marketing's brand
guide rather than assuming this purple. For internal data-team tools, this set is
correct and gives consistency with the portal the team already uses.

## Cross-links

- [[np-kb-branding]] — Pat's *personal* warm-light identity (use for his own
  properties; this skill overrides it for Campminder work tools).
- [[np-kb-intentional-design]] — the method (60-30-10, scarcity, anti-slop) that
  applies on top of these tokens.
- [[np-kb-data-team-mcp]] — sibling Campminder data-team surface.

When a new Campminder design decision proves out (a light theme, a new component,
an official color correction), fold it back here.
