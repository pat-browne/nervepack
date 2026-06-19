---
name: np-kb-chrome-extension-publishing
description: Rules for organizing assets in a Chrome MV3 extension repo and the Chrome Web Store submission asset checklist. Use when adding icons or promo art, packaging a build for upload, or auditing whether a repo is ready for store submission.
---

# Chrome extension publishing

For any Manifest V3 Chrome extension repo. Project-specific `CLAUDE.md`
files override where they conflict.

## 1. What ships in the bundle vs. what stays in source

Crxjs and Vite-style bundlers copy **only files that are referenced** from
the manifest or imported by source. Use this to your advantage:

| File class | Lives in | Referenced from manifest? | Ends up in `dist/`? |
|---|---|---|---|
| Toolbar / store icons (16, 32, 48, 128) | `assets/images/` | **Yes** — `action.default_icon` and top-level `icons` | Yes |
| README header, social card, marquee, promo tiles, favicons, design source PNGs | same `assets/images/` | **No** | No |

Keep both classes in the same folder. The bundler's reachability analysis
keeps the shipped extension small without needing a separate `marketing/`
directory. Verify with `npm run build && find dist -type f` after adding
any new image.

**Anti-pattern:** putting promo art under `public/` (everything in `public/`
is copied wholesale, regardless of references — Vite default).

## 2. Chrome Web Store submission asset checklist (MV3, 2025)

Full asset checklist, screenshot bit-depth gotcha, auth-free mockup approach, and resize notes: references/store-submission-checklist.md

## 3. Packaging command pattern

A single command produces both the load-unpacked-equivalent archive and the
Chrome Web Store upload zip:

```bash
npm run build && \
NAME=$(node -p "require('./package.json').name") && \
VERSION=$(node -p "require('./package.json').version") && \
(cd dist && zip -r "../${NAME}-v${VERSION}.zip" .)
```

**Use shell variables, not nested `$(node -p '...')` inside the path.** The
nested form `(cd dist && zip -r "../$(node -p 'require(\"../package.json\").version').zip" .)`
silently produces a zip named `meet-formatter-v.zip` (empty version) because
the escaped double-quotes break inside bash's double-quoted string. Always
materialize the version into a shell var first, then interpolate.

Add `*-v*.zip` (or the specific name) to `.gitignore` so build artifacts
don't get committed. Confirm with `unzip -l` that `manifest.json` is at the
zip root, not nested under a `dist/` folder — the CWS uploader rejects
nested manifests.

## 4. Manifest sanity checks before submission

- `description` is **≤132 characters**. CWS **silently truncates** the rest in the listing header — there's no rejection, no warning. Test the byte count in CI / build script: `node -p 'JSON.parse(require("fs").readFileSync("dist/manifest.json","utf8")).description.length'` should be ≤132.
- **Start version low.** For the very first submission, set `version` to something like `0.9.0` or `0.0.0.1` so you have lots of room to bump. CWS rejects re-uploads of the same version, so every iteration during review or after launch must bump. Starting at `1.0.0` works but burns your headroom on day one.
- `version` is bumped from the last submission (CWS rejects re-uploads of the same version).
- `host_permissions` are as narrow as possible — `<all_urls>` triggers a much slower review.
- If using `host_permissions`, the manifest must NOT also use `activeTab` for the same purpose — pick one.

## 5. Hand-off build at the end of every change cycle

When you finish a batch of extension changes, **always rebuild `dist/` and
repackage the zip, then hand it to the user for manual testing** — don't leave
them on a stale artifact. Treat "produce a fresh installable build" as the last
step of the cycle, the same way you'd run the test suite.

- **Bump the version on EVERY hand-off — even a test-only / no-code-change
  build.** Chrome keys "is this an update?" off `manifest.version`, and the user
  verifies what they loaded by reading the version in `chrome://extensions`.
  Handing off the *same* version twice is indistinguishable on reload — the user
  can't tell the fresh build from the stale one and reports a fix as "still
  broken" (this bit us twice: two `0.10.0`s, then two `0.10.1`s). So bump on each
  delivery (`npm version patch --no-git-tag-version` **and** the `version` in
  `manifest.config.ts`/manifest), even if the code is byte-identical — the point
  is a unique, verifiable marker. It's cheap and pre-release; consolidate at
  actual submission.
- **Tell them how to load it cleanly:** remove the old unpacked extension first,
  load the new zip/`dist/`, then reload the host tab (a content-script change
  only reaches already-open tabs after reload or SW re-injection).
- Rebuild from a **clean tree at a known commit** so the artifact matches what's
  pushed; the zip is gitignored (`*-v*.zip`).

## 6. Migrate stored data across updates — `chrome.storage` survives upgrades

When a new version changes the *shape* of persisted data, old storage survives and must be read-migrated — never wiped. This is the MV3 instance of the general rule in [[np-kb-coding-rules]] §7.

Migration pattern, worked example, and upgrade-test requirements: references/storage-migration.md

## See also

- [[np-kb-chrome-extension-content-script]] — defensive patterns for MV3 content scripts (context invalidation, recycled-DOM idempotency)
- [[np-kb-github-pages-custom-domain]] — host the required `PRIVACY.md` on a custom subdomain
- [[np-kb-coding-rules]] — the long-form canon; apply on top of these for any code changes
