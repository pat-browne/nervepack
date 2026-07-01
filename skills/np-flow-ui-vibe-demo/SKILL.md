---
name: np-flow-ui-vibe-demo
description: Before finishing ANY change that modifies a UI, show the final product as a live demo and pull the human's in-page notes from the Vibe Annotations tool (~/.vibe-annotations/annotations.json) — address them, then finish. Use whenever you touch a user-facing surface (web app/dashboard, tool UI, browser extension, site) and are about to call it done or open a PR. Backend-only changes are exempt.
---

# Demo UI changes for Vibe feedback before finishing

**The rule (Pat asked for this explicitly):** any change that modifies a **UI**
gets a **live demo + Vibe visual pass** before it's "done" or PR'd. Don't finish a
UI change on green unit tests alone — run the real thing, look at it, and fold in
the human's in-page notes.

**Backend-only changes are exempt** (APIs, ingestion, scripts, infra): no UI, no
demo required.

## The pass

1. **Run the real product** — start the actual app/stack (not just tests) so the
   change is visible in the browser/UI it ships in.
2. **Drive it to the changed surface** — reproduce the feature/fix on screen
   (Playwright is fine for this: navigate, interact, screenshot each state).
3. **Pull Vibe annotations** — read `~/.vibe-annotations/annotations.json`:
   - If the human has left in-page notes, **address each**, then re-verify.
   - If the file is absent/empty, **present the demo (screenshots) and invite a
     Vibe pass** — leave the stack running so they can annotate; don't declare
     "done" as if it were reviewed.
4. **Then finish** — only after the visual pass do you wrap up / open the PR
   (finishing goes through a PR, never a local merge — see [[np-kb-git-discipline]]).

## Notes

- Don't build a custom annotation overlay — the Vibe Annotations tool
  (`~/.vibe-annotations/annotations.json`) is the source of in-page notes.
- This is the general form of the visual-pass step in [[np-flow-web-post-review]]
  (which applies it to blog posts): the same discipline holds for **any** UI —
  dashboards, internal tools ([[np-kb-campminder-brand]]), extensions, sites.
- Pairs with [[np-kb-git-discipline]]: demo (this skill) → then land via PR.
