---
name: np-kb-browser-extension-monetization
description: How to monetize a privacy-respecting browser extension — voluntary tipping via a link-out (Ko-fi now, Stripe Payment Link later) behind one swappable constant, never an in-extension payment SDK; plus the lifecycle-prompt pattern (install clock, in-popup review/tip banners, snooze-then-retire) with no scary permissions. Use when adding tipping/donations, a "rate us"/feedback prompt, or any revenue path to a Chrome/MV3 extension, so it defaults to the approach already shipped instead of reinventing it.
---

# Monetizing a privacy-respecting extension

The extensions this skill covers are free and privacy-respecting (no ads, no tracking, no
selling data) — which means they earn nothing on their own. The monetization
model is therefore **voluntary tips**, kept optional so the tool stays free for
those who can't tip. Everything below is the default; the worked example is
`pat-browne/meeting-template`.

## Link out — never embed a payment SDK

The Chrome Web Store **retired its in-app payments / licensing API** years ago;
in-extension payment for digital goods is no longer supported. The standard,
policy-safe pattern is to **open a hosted payment page in a new tab**:

```ts
function openUrl(url: string) {
  if (typeof chrome === 'undefined' || !chrome.runtime?.id) return  // context guard
  try { void chrome.tabs.create({ url }) }
  catch (e) { if (!/Extension context invalidated/i.test(String(e))) throw e }
}
```

Why not embed a checkout in the popup: it fights the MV3 popup CSP, adds a
third-party script dependency, and invites store-review scrutiny — the opposite
of "low friction." A link-out ships **no payment code**, so it needs no new
manifest permissions and leaves your DOMPurify/sanitizer boundary untouched.
The CWS payments policy is **silent** on external links (it neither grants nor
forbids them) but does require you make clear that **you, not Google, are the
seller** and disclose any paywalled functionality — see
[[chrome-web-store-payments-policy]]. The "retired in-app payments API" framing
is engineering context, not a policy quote.

## One swappable constant

Keep the payment target in a single config constant so switching providers is a
one-line change:

```ts
export const TIP_URL = 'https://ko-fi.com/<handle>'   // → Stripe Payment Link later
```

### Provider choice (one-time tips)

| Provider | Platform fee | Notes |
|---|---|---|
| **Ko-fi** | **0%** (processor fee only) | Low friction, no account needed to give. Good default to start. |
| Buy Me a Coffee | 5% flat | Strong brand; many already have accounts. |
| GitHub Sponsors | 0% but Stripe-gated to ~70 countries | Dev-native; reads as "sponsor," not a quick tip. |
| **Stripe Payment Link** | ~2.9%+30¢, no platform fee | Your own branded checkout. Move here when you want branding/control. |

For Stripe **implementation** (Payment Links, Checkout, webhooks) use the
`stripe` Claude plugin (its skills + MCP) and `context7` — do **not** ingest
Stripe docs into `sources/` or hand-roll the integration; those tools cover it
live and version-current.

## Tip entry points and the "already tipped" proxy

Surface tipping in **two** places: a persistent settings/cog menu item, and a
timed prompt (below). You **cannot detect a real payment** from a link-out (no
server/webhook, and adding one breaks the privacy posture). So "has tipped" =
**clicked the tip link**. Store a **counter + timestamp** (not a boolean) —
`tipClicks`, `lastTippedAt` — so you can suppress the tip prompt after a click
*and* later re-prompt a long-installed user who only tipped once. Persist the
count from the functional state update so it can't drift on rapid clicks.

## Lifecycle prompts (review + tip), done politely

- **Install clock:** set `installedAt` in `chrome.runtime.onInstalled` — always
  on `reason === 'install'`; on `update` only **if missing**, so existing users
  start the clock at the upgrade and never get a day-0 prompt.
- **Surface in-popup, not via notifications.** A dismissible banner at the top
  of the popup needs no permissions. The `notifications` permission adds a
  scary line to the store listing and is easy to ignore at the OS level — skip
  it.
- **State machine (pure, time-injected):** `pending → snoozed → done`. "Maybe
  later" snoozes ~14 days then retires after the one reminder; acting or
  dismissing retires immediately. Show **at most one** banner at a time;
  prioritize the review prompt over the tip prompt.
- **Sane default cadence:** day-60 review/feedback ("a quick CWS rating helps;
  hit a snag? email me"), day-90 tip. Feedback path = `mailto:` to the
  registered developer email; review path = `https://chromewebstore.google.com/detail/<ID>/reviews`
  (the `<ID>` only exists once the item is created in the dashboard — placeholder
  until then). Keep prompt copy short and bold.

## Worked example

`pat-browne/meeting-template`: `src/lib/config.ts` (`TIP_URL`, `FEEDBACK_EMAIL`,
`CWS_REVIEW_URL`, day thresholds), `src/lib/prompts.ts` (the state machine),
`src/popup/SettingsMenu.tsx` (cog menu), and the day-60/90 `PromptBanner`s wired
in `App.tsx`.

## See also

- [[np-kb-chrome-extension-publishing]] — store assets + submission checklist
- [[np-kb-chrome-extension-content-script]] — defensive injection patterns for the same extensions
- The `stripe` plugin — for the Stripe side when you graduate from Ko-fi
