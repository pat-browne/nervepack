# np-core-sync — layer and manifest behavior details

**The personal content overlay gets the same ff-only treatment** as team
layers, gated by `sync.content` (default on; no-op on a single-repo legacy
layout). No layer or the engine ever auto-pushes — `np_sync.py` has no push
code path. Layer outcomes are non-fatal stderr notes, not the status file
(engine-only): `"content layer <path> not fast-forwarded (diverged/ahead/no
upstream) — left as-is"` / `"... has local edits — skipping pull"`.

Every sync also validates each layer's `.nervepack/layout.json` (the same
check `cli.py doctor`'s `layer-layout` capability runs) and prints
`"layout manifest invalid in <path>: <error>"` to stderr on a corrupt
manifest. This is non-fatal, like the layer notes above. Surface this line to
the user if you see it: a bad manifest silently misplaces the next
[[np-core-contribute]] write into that layer.
