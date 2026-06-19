---
name: np-kb-reader-friendly-monetization
description: Principles for non-intrusive, reader-first web display-ad monetization and readable long-form layout — the guardrails that keep ads (and the page) from hurting the reader or Core Web Vitals. Use when adding or placing ads on a content site/blog, choosing ad density/formats, configuring AdSense Auto ads, reserving ad-slot space, or designing a post/reading layout (column width, alignment, images). Web-display-ads sibling of the extension-tipping skill.
---

# Reader-friendly, non-intrusive web monetization

**Throughline: revenue follows the reader.** A stable, readable, uncluttered page
earns more over time than an aggressive one — and aggressive ad experiences are
*enforced against* (Chrome blocks all ads on a Failing site). Treat the guardrails
below as hard constraints, not suggestions. Knowledge depth + RPM/network/placement
strategy live in the wiki [[content-site-monetization]]; this skill is the behavior.

## 1. Non-intrusive ads — Better Ads Standards ([[better-ads-standards]])
Never ship a prohibited ad experience:
- **No** pop-ups, prestitial/postitial-with-countdown, full-screen scroll-over,
  auto-play video **with sound**, flashing animated, or large sticky ads.
- **Mobile ad density ≤ 30%** of main-content height (Σ ad heights ÷ main-content
  height — measured against content, not viewport).
- A **sticky anchor** ad is OK **only if small + dismissible** ('×').
- Enforcement is real: a **Failing Ad Experience Report → Chrome filters *all* ads**
  on the site (≈30-day grace on first failure, shrinking after).

## 2. No layout shift — CLS ([[core-web-vitals]])
Ads are the **#1 cause** of Cumulative Layout Shift. Target **CLS ≤ 0.1**.
- **Reserve every ad slot's space** up front with a fixed `min-height` (or
  `aspect-ratio`) container; never collapse it when empty.
- Set `width`/`height` (or `aspect-ratio`) on **all** images/media so space is
  reserved before load.
- **Never inject content above** what the reader is reading (except in direct
  response to a user interaction — those shifts are exempt within 500 ms).

## 3. Reader-first placement
- Ads go **beside or below** content — **never interrupting** a sentence, list, or
  paragraph; anchor to document structure, not raw word count.
- **Label every ad** clearly ("Advertisement") and give it an `aria-label`.
- **Viewability > slot count:** 3–4 well-placed, in-view units beat a dozen poor
  ones (~30% RPM uplift from viewability alone). Keep a sane content-to-ad balance;
  ads must never **mimic content** or sit where they cause **accidental clicks**.

## 4. Readable reading column ([[web-readability-typography]])
- **Cap the prose measure to ~66ch (~700px)** — WCAG 1.4.8 caps line width at ≤ 80
  chars; a full-bleed text column (~110 chars) is too wide to track.
- Body **16–20px**, **line-height ≥ 1.5** (unitless).
- **Do NOT justify body text** on the web — `text-align: justify` without real
  hyphenation + adequate measure causes "rivers"; **WCAG 1.4.8 (AAA) explicitly
  forbids justified text.** Left-align (ragged-right).
- Images **punctuate** the column (see [[np-kb-branding]] image-zone/float rules);
  lightboxes/popovers must be **dismissable + persistent** (WCAG 1.4.13).

## 5. AdSense Auto ads — configure, don't trust defaults
Auto ads can inject formats that *violate* the above if left default:
- **Disable vignette/interstitial** formats (prestitial-like) in the AdSense console.
- Keep the **anchor** format **dismissible**; cap overall density.
- Ensure Auto-ad containers **reserve space** (CLS) — prefer space-reserved **manual**
  placements where you need control; let Auto ads fill, not dominate.

## 6. Consent (CMP) — one is enough, never stack
For EEA/UK/CH traffic, Google **requires a certified, TCF-integrated CMP** (enforced —
a Failing site gets Chrome ad-filtering). Key facts:
- **One CMP serves every network.** A TCF consent string is read by *all* registered
  vendors (Google, Sovrn, every SSP). You never need one CMP per ad network — **running
  two conflicts** (both fight over `window.__tcfapi`).
- **Google's built-in "Privacy & messaging" CMP is enough** — it's certified, ships
  through the `adsbygoogle.js` tag (no extra code), and covers Google + TCF vendors +
  Google's non-TCF partners (via the Additional Consent string).
- Go third-party (CookieYes, iubenda, Usercentrics, Sourcepoint…) only for theming /
  granular control / **US-state GPP** coverage (TCF is EU-only). Still **one** CMP.
- Must be **TCF v2.3** (IAB deadline 2026-03-01) or TC strings are treated invalid →
  Limited Ads. Verify v2.3 before wiring any third-party CMP.

## ads.txt operational note
`ads.txt` lives at the site root (`/ads.txt`, `text/plain`). AdSense "Not found" usually
means **Google last crawled before the file existed** — it updates on the next crawl
(a day+), not a config bug. Don't edit a correct file (resets the clock); confirm the
site URL in AdSense matches where the file lives, and nudge via Search Console.

## Related
- [[np-kb-browser-extension-monetization]] — the *extension* surface (voluntary
  tipping link-out); this skill is its web-display-ads sibling.
- [[np-kb-branding]] — visual/layout defaults (image zones, floats, tokens).
- [[np-kb-wiresandwizards-site]] — the applied implementation (Astro blog).
- Sources: [[better-ads-standards]], [[core-web-vitals]],
  [[web-readability-typography]], [[wcag-2-2]]; synthesis [[content-site-monetization]].
