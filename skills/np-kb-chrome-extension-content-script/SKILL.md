---
name: np-kb-chrome-extension-content-script
description: Defensive patterns for Chrome MV3 content scripts that have to survive host-app surprises — extension reloads orphaning the chrome.* namespace, host frameworks recycling DOM elements between component instances. Use when writing or debugging any content script that injects into a third-party page or holds long-lived observers/listeners.
---

# Chrome MV3 content script robustness

Content scripts live in someone else's page, with the extension runtime
attached only as long as Chrome decides to keep it attached. Two recurring
failure modes that will absolutely bite a naive content script:

## 1. "Extension context invalidated"

When Chrome reloads or updates the extension (dev refresh, Chrome Web Store
auto-update), the **old copy of your content script keeps running on the
page**. Its `chrome.*` namespace is now disconnected. Every `chrome.*` call
throws `Error: Extension context invalidated.` — and if those calls happen
inside a `MutationObserver` or `setInterval` callback, the rejection is
**unhandled** and surfaces as a noisy console error on every DOM mutation
until the user navigates away.

### The probe

`chrome.runtime?.id` evaluates to `undefined` the moment the context dies.
It's truthy as long as the context is alive. Cheap, sync, no try/catch
needed.

```ts
function isContextValid(): boolean {
  return typeof chrome !== 'undefined' && !!chrome.runtime?.id
}
```

### The two-layer defense

1. **Wrap every `chrome.*` call site** with the probe up front AND a
   try/catch around the await. The probe catches the common case (context
   dead before the call); the catch handles the race where the context
   dies *during* an in-flight `await`.

   ```ts
   export async function getSettings(): Promise<Settings> {
     if (!isContextValid()) return defaultSettings
     try {
       const result = await chrome.storage.sync.get(KEY)
       return { ...defaultSettings, ...result[KEY] }
     } catch (e) {
       if (/Extension context invalidated/i.test(String(e))) return defaultSettings
       throw e
     }
   }
   ```

2. **Tear down long-lived listeners on first detection.** Any
   `MutationObserver`, `chrome.storage.onChanged`, `chrome.runtime.onMessage`
   subscription, or interval will keep firing in the orphaned script until
   the user navigates away. Without teardown, the same error throws on
   every fire.

   ```ts
   let observer: MutationObserver | null = null
   let unsubSettings: (() => void) | null = null

   function teardown() {
     observer?.disconnect(); observer = null
     unsubSettings?.(); unsubSettings = null
   }

   function onMutation() {
     if (!isContextValid()) { teardown(); return }
     // ... do work
   }
   ```

   Call `teardown()` from **every** entry point's `isContextValid()`
   guard. One miss and the script stays noisy.

Limitations and re-injection notes: references/focus-lifecycle-detail.md.

## 2. Don't gate injection on dataset flags when the host app recycles DOM

A natural-looking pattern: when you inject into an element, mark it
`element.dataset.alreadyInjected = 'true'`; check that flag to prevent
double-injection on subsequent `MutationObserver` fires.

**This breaks when the host app uses React-style component recycling.**
The same DOM element gets reused for a different "instance" of the same
component — your dataset flag persists on the recycled node, even though
the user-visible content has been reset. Your next injection (which the
user expects) silently skips because the flag is sticky.

Real-world example: Google Calendar reuses the event-modal contenteditable
across new-event dialogs. A dataset-flag gate on the first auto-insert
means every subsequent new-event creation gets skipped.

### Better: compare current content to incoming content

Use content equality, not a sticky flag, for idempotency. All injection
must go through your DOMPurify-sanitized boundary (the rule from
[[np-kb-chrome-extension-publishing]]); the helper below assumes `incomingSanitized`
has already passed through it.

```ts
// `incomingSanitized` is the output of markdownToSanitizedHtml(...) or
// equivalent — never call this with raw user input.
function writeIfDifferent(el: HTMLElement, incomingSanitized: string) {
  if (el.innerHTML === incomingSanitized) return  // idempotent, skip
  // safe: only callers that pass DOMPurify-sanitized HTML are allowed
  // eslint-disable-next-line no-unsanitized/property
  el.innerHTML = incomingSanitized
}
```

For richer rules (e.g. "replace if empty, append if user-typed, skip if
auto"), normalize both sides (trim + collapse whitespace) and branch on
that — never on a flag whose lifetime you don't control.
Normalize helper: references/focus-lifecycle-detail.md.

### When a sticky flag IS fine

If the element is owned and rendered by your extension (not the host
app), dataset flags are fine. The rule is specifically: don't trust state
on DOM nodes the host app controls.

## 3. The host app steals focus back right after you set it

When you programmatically move focus (e.g. focus a title field after
injecting content), a host SPA can run its own focus pass on the next
frame and steal it back — especially on a **cold page load**, where the
host is still hydrating and your target may have mounted only a beat ago.
A single synchronous `element.focus()` loses that race. The tell: focus
works on warm / subsequent interactions but **not on first load**.

### Re-assert across a short animation-frame window, superseded by a token

Don't focus once — re-assert for a handful of frames so a late steal (or a
late-mounting target) is recovered. Guard with a module token so a newer
action, or the user starting to interact, supersedes the loop — you must
never fight the user once they've moved on:

Full `focusResiliently` implementation and re-fire guidance: references/focus-lifecycle-detail.md.

## 4. Routing a message from the service worker to "the" content-script tab — broadcast, don't pick one

When a popup/SW needs to reach the content script on a host site, the tempting
shortcut is `tabs.query({url})` then send to the **first** result:

```ts
const tabs = await chrome.tabs.query({ url: HOST_MATCH })
const id = tabs.find(t => typeof t.id === 'number')?.id   // ← BUG with >1 tab
await chrome.tabs.sendMessage(id, msg)
```

This silently breaks when the user has **more than one** tab on that host: the
first match may be the wrong one (e.g. a list/week view), and `sendMessage`
**resolves successfully** because that wrong tab *does* have a listener — it just
has nothing to act on. The user sees "nothing happens" with no error. (Real case:
Google Calendar with two tabs open — inserts went to the non-editor tab.)

Don't try to guess the "active" tab either: `active: true` / `lastFocusedWindow`
are unreliable while the extension **popup** is open (the popup isn't a tab, and
focus semantics vary).

**Fix: broadcast to every matching tab.** Make delivery idempotent on the
receiving side (the content script no-ops unless the relevant surface/editor is
actually present), so hitting idle tabs is harmless:

```ts
const ids = (await chrome.tabs.query({ url: HOST_MATCH }))
  .map(t => t.id).filter((id): id is number => typeof id === 'number')
await Promise.all(ids.map(id => deliver(id, msg)))   // deliver = send, inject+retry on failure
```

The content script must guard its action on real page state (`findSurface()` /
editor present), never assume "I got the message, so the editor is here."

## See also

- [[np-kb-chrome-extension-publishing]] — packaging and CWS submission for the same MV3 extensions
- [[np-kb-browser-extension-monetization]] — tipping/prompts UX for the same extensions
