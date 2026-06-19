---
name: np-kb-asset-sourcing
description: How to add real images and icons to a project by pulling them from a source — stock photos via a provider API (Pexels default, Unsplash swap) behind one swappable constant, and icons via Iconify/astro-icon (Lucide) — with a dormant-safe fetch-script pattern, Astro src/assets optimization, and an images[] content field. Use when a site/blog needs real photos or proper SVG icons instead of emoji/gradient placeholders, or when wiring per-post imagery.
---

# Asset sourcing — real images & icons

The proven pattern for giving a project real imagery without hand-collecting files:
**pull photos from a stock API** and **render icons from an Iconify set**, both behind
seams so the project still builds with nothing configured. First shipped on
[[np-kb-wiresandwizards-site]] (Astro 5). Pairs with [[np-kb-branding]] for the look.

## Images — provider behind one swappable constant

- **Default provider: Openverse — keyless.** The Creative-Commons aggregator
  (`https://api.openverse.org/v1/images/?q=…&license_type=commercial,modification`)
  needs **no API key** (anonymous, rate-limited), so images can ship *now*. Real,
  subject-relevant results (Flickr/Wikimedia/etc.). The cost: images are CC-licensed, so
  **attribution is legally required** — keep `IMAGE_CREDITS_VISIBLE` on and render
  author + license + a link to the source. (Display/resize/CSS-tint is reproduction, not
  an SA-triggering derivative, so BY-SA needs attribution but not site relicensing.)
- **Keyed alternates: Pexels / Unsplash.** Higher curation, attribution optional
  (Pexels), but need a free API key from [[np-env-secrets-refresh]] (Bitwarden) in
  `PEXELS_API_KEY` / `UNSPLASH_ACCESS_KEY`. Use when quality matters more than zero-setup.
- The provider is **one constant** (`IMAGE_PROVIDER`), mirroring the ads/comments/
  newsletter seams — swap it, don't rewrite call sites. `isFetchEnabled(env)` returns
  true for keyless providers and key-gates the rest.
- **Dormant-safe:** with no usable provider and no fetched images, posts fall back to
  their icon/placeholder — the build is unaffected.

### The fetch-script pattern (`scripts/fetch-images.mjs`)

A small Node CLI, **not** a build step. Hard rules learned in review:

- **Prints a frontmatter block to paste — never edits content Markdown.** Keeps content
  edits human-reviewed; the script only downloads files + emits the `images:` YAML.
- **No-ops (exit 0) when the key is absent** — never hard-fails a build.
- **`--dry-run`** prints chosen URLs + credits without downloading.
- **Harden the I/O** (each of these *was* a real review finding):
  - `arg()` must reject a flag whose "value" is the next flag (`--slug --query` →
    don't set slug to `--query`): `const val = argv[i+1]; return (val && !val.startsWith('--')) ? val : def;`
  - **YAML-escape every interpolated string** (photographer name, alt, url) — strip
    newlines + escape quotes — or one `"` in a name breaks `astro build`:
    `const yamlSafe = s => String(s ?? '').replace(/[\r\n]+/g,' ').replace(/"/g,"'");`
  - **Check `img.ok` before writing** — else an HTTP error body lands as a `.jpg` and
    the image optimizer fails with a confusing format error.
  - **Emit the `src:` path relative to the *post* `.md`, not the asset dir.** Files save
    to `src/assets/posts/<slug>/` but the post lives in `src/content/posts/`, so the
    pasted `src` must be `../../assets/posts/<slug>/<n>.<ext>` — a bare `./<n>.jpg`
    resolves next to the `.md` and fails. Derive `<ext>` from the download URL (CC
    sources serve png/webp too), don't hardcode `.jpg`.
  - **Curate before publishing.** CC/stock results vary — fetch a few extra, build a
    contact sheet (sharp from the project's `node_modules`), eyeball for relevance/
    quality, drop the rejects, and write descriptive `alt` (the provider's photo *title*
    is not good alt text). `images[0]` becomes the card thumbnail, so make it the
    strongest/most on-brand shot.
- Stores into `src/assets/posts/<slug>/<n>.jpg` (Astro `src/assets`, **not** `public/`,
  so the build pipeline emits responsive AVIF/WebP).

### Content model (Astro)

- Schema gains `images: z.array({ src: image(), alt: z.string(), credit?: {source,
  author, url} }).max(5).default([])`. Using `image()` **requires the function-form
  schema** `schema: ({ image }) => z.object({…})` — the static `z.object(…)` form has no
  `image()`.
- **`images[0]` is the canonical thumbnail / featured image**; the in-post gallery
  renders the full set (the post page doesn't otherwise show `images[0]`, so showing
  all of them there is not in-page duplication — index card/featured is a different
  page). Empty array (default) = dormant fallback.
- Render with `<Image>` from `astro:assets` (needs `ImageMetadata`, i.e. the schema's
  `image()` output — not a string path). Give `.gallery` items an `aspect-ratio` so
  `object-fit: cover` can't collapse.
- **`fit` per image (cover vs contain).** `object-fit: cover` fills a fixed card slot by
  cropping — right for photos, but it lops the sides off a **wide banner/logo** (e.g. a
  ~2.6:1 marquee in a ~1.5:1 featured panel). Add an optional `fit: 'cover' | 'contain'`
  to the image schema (default `cover`, so photos are untouched) and set banners to
  `contain` (+ a little padding) so the whole graphic shows. Pass it through to the card
  component as a class. Same idea works for the small feed thumbnail.
- **Attribution:** store `credit` always; a global `IMAGE_CREDITS_VISIBLE` (default
  off) toggles a per-image credit line; a site-wide "Photos via <provider>" footer note
  covers courtesy attribution.
- **Inline body images need a caption mechanism to carry a credit.** A plain
  `![alt](src)` and a bare hero render no attribution; only the gallery component (walking
  the `images[]` array) emits a credit line by default. So a CC-licensed image either goes
  in frontmatter `images[]` (gallery, credit auto-rendered) **or** is placed inline *with*
  a caption that shows the attribution. The cheap, generic inline path: a ~15-line rehype
  plugin that turns a titled image `![alt](src "Author · CC BY-SA 4.0")` into a
  `<figure>`+`<figcaption>` — Astro still optimizes the image, and the required credit
  renders at the image, so the "distribute inline" house style applies to CC photos too
  (see [[np-kb-wiresandwizards-site]] `rehype-img-caption.mjs`). Without such a plugin,
  fall back to frontmatter `images[]`. When sourcing a brand-new or highly specific
  subject that keyless stock can't supply (e.g. a just-revealed product), **Wikimedia
  Commons** often has a usable CC BY-SA photo — attribute it like any other CC source.

## Icons — Iconify via `astro-icon` (Lucide)

- `npm i astro-icon @iconify-json/lucide`; add `integrations: [icon()]` to
  `astro.config.mjs`; render `<Icon name="lucide:wand-sparkles" />` from
  `astro-icon/components`.
- Store icon ids as data (`icon: 'lucide:cpu'`), not emoji — any Iconify set works, not
  just Lucide. A **bad icon name fails the build loudly** (good: caught deterministically).
- Lucide SVGs use `currentColor`, so they inherit the theme text color. Size with
  `:global(svg){width:1em;height:1em}` and one `font-size` source of truth (astro-icon
  injects scoped-CSS-opaque inline SVG, hence `:global`).
- MIT, no attribution.

## On-brand treatment

Real photos can clash with a styled theme. Apply a **reversible CSS tint** at render
time — a low-opacity gradient `::after` using the theme's `--*-rgb` tokens with
`mix-blend-mode: overlay` and `pointer-events: none` — so originals stay clean on disk
and the tint is one selector to remove. (Keeps the no-literals token rule intact.)

## Related

- [[np-kb-wiresandwizards-site]] — first consumer; concrete files (`images-config.mjs`,
  `fetch-images.mjs`, `PostGallery.astro`).
- [[np-kb-branding]] — icon style + the tint-token discipline.
- [[np-env-secrets-refresh]] — pulling the provider API key from Bitwarden.
