# Chrome MV3 content script — extended detail

## Context-invalidated: what the two-layer defense does NOT solve

- The orphaned script can't recover. By design — Chrome's MV3 lifecycle
  expects the next page navigation to load the fresh script. The defense
  is just "stop screaming until then."
- New content scripts injected after an update need to be injected
  programmatically into already-open tabs via `chrome.scripting.executeScript`
  from the service worker (declarative `content_scripts` only fires on
  navigation). See [[np-kb-chrome-extension-publishing]] for the `scripting`
  permission justification.

## DOM injection: normalize helper

For richer idempotency rules (e.g. "replace if empty, append if user-typed,
skip if auto"), normalize both sides before comparing — never on a flag
whose lifetime you don't control:

```ts
function normalize(input: HTMLElement | string): string {
  if (typeof input === 'string') {
    const tmp = document.createElement('div')
    tmp.textContent = input  // measuring text length, no need to render HTML
    return (tmp.textContent ?? '').trim().replace(/\s+/g, ' ')
  }
  return (input.textContent ?? '').trim().replace(/\s+/g, ' ')
}
```

## Focus resiliency: full token-guarded rAF implementation

```ts
let refocusToken = 0
function cancelRefocus() { refocusToken++ }   // call on declined/aborted actions

function focusResiliently(findTarget: () => HTMLElement | null) {
  const token = ++refocusToken
  const step = (left: number) => {
    if (token !== refocusToken) return          // superseded — stop
    findTarget()?.focus()
    if (left > 0 && typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => step(left - 1))
    }
  }
  step(6)                                        // ~6 frames ≈ 100ms
}
```

Re-assert on **idempotent re-fires** too: the host's open-burst fires your
MutationObserver repeatedly with unchanged content, so restart the short
loop on each — that keeps the steal window covered for the whole burst.
The moment the user edits and your injection path goes to "skip," call
`cancelRefocus()` so the loop dies and focus stays where the user put it.

This is timing-dependent and only reproduces against the real host page:
unit-test the *mechanism* (an idempotent re-fire re-focuses the target),
then verify the cold-load race live.
