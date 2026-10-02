## Conflict policy

If the push is rejected as non-fast-forward:
1. `git -C "$REPO" pull --rebase --autostash`
2. If conflicts: surface them to the user; do not auto-resolve content
   conflicts in `SKILL.md` files (those are user intent).
3. Retry push.
