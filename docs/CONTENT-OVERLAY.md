# Content & team overlays

The engine (`~/Code/nervepack`) is shared machinery. Your skills, sources, memory, and
metrics live in a separate **content overlay** so they stay yours and sync on your own
repo. Configuring one is optional but recommended — skip it and the engine falls back to
its own root, which works but gives you nowhere personal to grow.

Part of the [getting-started](GETTING-STARTED.md) walkthrough.

## Personal overlay

Tell the engine where your content lives:

```bash
mkdir -p ~/.config/nervepack
echo "$HOME/Code/nervepack-content" > ~/.config/nervepack/content-dir
```

The `mkdir` is required the first time — `>` creates the *file* but not its parent
directory, so writing `content-dir` into a `~/.config/nervepack` that doesn't exist yet
fails with `no such file or directory`.

No overlay yet? Fork
[`nervepack-content-example`](https://github.com/pat-browne/nervepack-content-example),
rename it to something private, and point at that.

## Team overlay (optional)

You can point at a *second*, shared overlay that sits above your personal one:

```bash
echo "$HOME/Code/team-nervepack-content" > ~/.config/nervepack/team-dir
```

The stack becomes **team > personal > engine**. Reads merge with the team winning (a team
skill or playbook shadows your personal one of the same name), and writes still land in
your personal overlay unless you explicitly "save to the team layer." This is dormant
until a team dir resolves, and enabled by the `team` toggle.

For a nested organization, the value can be a **comma-separated list of up to four team
dirs**, highest-precedence first:

```bash
echo "$HOME/Code/squad-content,$HOME/Code/division-content,$HOME/Code/org-content" \
  > ~/.config/nervepack/team-dir
```

That stacks **squad > division > org > personal > engine** (the leftmost wins a name
clash). More than four team dirs is a hard error — the session falls back to
personal-only, and `np-doctor.sh` flags the invalid config.

## Verify

```bash
python3 ~/Code/nervepack/engine/setup/np-path-check.py ~/Code/nervepack ~/Code/nervepack-content
```

Passing your overlay as a second argument checks that its skills and docs resolve too,
not just the engine's. A clean run prints `all setup/onboard path references resolve ✓`.
