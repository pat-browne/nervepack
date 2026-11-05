# Layer resolution detail

- **personal content overlay** — the default target for domain knowledge
  (`np-kb-*`/`np-env-*` skills, `wiki/`, `sources/`). Resolve it:
  `CONTENT="$(python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/np_content.py" content_dir)" || { echo "no content overlay resolved" >&2; exit 1; }`
  (single-repo layouts resolve to the engine root, so the same paths work).
  Check the exit status rather than assuming: `content_dir` exits 1 when it
  cannot resolve, and an unchecked `$CONTENT` is then empty, so every path built
  from it silently becomes a relative one rooted at the current directory.
- **team overlay** — only for a shared team convention ("save to the team layer",
  "this is a team rule", `--layer team`): resolve with `np_content.py team_dir` (same resolver).
  If that errors, STOP and tell the user the team layer isn't configured
  (`NP_TEAM_DIR` / `~/.config/nervepack/team-dir`) — never silently fall back to
  personal. Team overlays have the same shape; relink/index are team-aware.
