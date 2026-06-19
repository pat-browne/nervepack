# Chrome Web Store submission asset checklist (MV3, 2025)

| Asset | Spec | Required? |
|---|---|---|
| Store icon | 128×128 PNG | Required |
| Screenshots | 1280×800 **or** 640×400, **24-bit PNG (no alpha)** or JPEG, 1–5 of them | Required (≥1) |
| Small promo tile | 440×280 PNG/JPEG | Required to appear in Featured / search promo slots |
| Marquee promo tile | 1400×560 PNG/JPEG | Optional |
| Privacy policy URL | Live HTTPS URL | Required whenever the manifest declares `storage`, `host_permissions`, `tabs`, or any user-data-touching permission. Even a single-host extension that makes zero network calls needs one. |
| Detailed description | ≤16,000 chars | Required |
| Single-purpose statement | Free text | Required |

**Screenshot bit-depth gotcha.** CWS rejects 32-bit RGBA PNGs. Verify with `file *.png` — should print `8-bit/color RGB`, NOT `RGBA`. Playwright's default `page.screenshot()` produces RGB-no-alpha; if you've been compositing, use `sharp(...).flatten({ background: '#fff' }).png()` or a Chromium canvas flatten before saving.

**Screenshots without real-app auth.** When the screenshot needs to show your extension running inside a logged-in third-party app (Calendar, Gmail, etc.) and driving real auth through Playwright is painful (Google's WebDriver-detection, 2FA), fall back to a polished static-HTML mockup that mirrors the host app's modal styling and embeds your project's actual sanitized output (via the same `marked` + `DOMPurify` pipeline the extension uses). One-shot render via Playwright `setContent` → `screenshot`. Reproducible, no auth, byte-identical content to what gets injected. Faster to iterate than fighting login flows.

Do not auto-resize promo art with `convert`/`magick` unless ImageMagick is already on the box — most fresh Ubuntu installs don't have it. `sharp` is also rarely a dep. Surface the gap to the user; they usually want to recompose in their design tool rather than letterbox-crop.
