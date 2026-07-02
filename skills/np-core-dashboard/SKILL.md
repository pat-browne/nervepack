---
name: np-core-dashboard
description: Launch or open the nervepack performance dashboard on demand, and explain its SessionStart auto-open behavior. Use when the user says "open the dashboard", "launch the nervepack dashboard", "show me the metrics", "/np-dashboard", or asks "why didn't the dashboard launch / open on session start". Covers the manual open path, the once-per-boot SessionStart guard, served (http) vs static (file://) modes, and the dashboard_open / dashboard_serve / dashboard_port toggles.
---

# Opening the nervepack dashboard

The performance dashboard renders `dashboard/data/metrics.jsonl` (evaluator output)
as charts + a suggestions panel. There are **two open paths** and a deliberate
once-per-boot guard — knowing which is which answers "why didn't it open?".

## Open it now (manual, always works)

```bash
bash ~/Code/nervepack/engine/setup/open-dashboard.sh
```

This rebuilds `metrics.js` from the latest metrics, resolves the URL, and opens it.
It has **no boot guard** (a single deliberate open can't start the reconnect loop the
SessionStart hook guards against — see below), so it opens every time you run it.
`NP_DASH_OPENER` overrides `xdg-open` (e.g. for a headless box / test).

## Why it doesn't auto-open every session

The SessionStart hook `engine/setup/74-open-dashboard.sh` opens the dashboard **at most once
per OS boot**, not once per session. It records the boot id in
`~/.cache/nervepack/dashboard-open-boot`; every later session start this boot sees a
matching marker and exits before opening. This is load-bearing: under remote-desktop,
opening a GUI browser on every SessionStart triggers an auto-reconnect → new session →
re-fire → reopen feedback loop (~150 sessions in seconds). The boot marker severs it.
(Full rationale: [[np-kb-claude-headless-scripting]] §4.)

So "it didn't launch on session start" is almost always **expected** — it already
launched on the first session after the last reboot. To diagnose:

```bash
cat ~/.cache/nervepack/dashboard-open-boot   # last boot it opened for
cat /proc/sys/kernel/random/boot_id          # current boot — equal ⇒ already opened
```

**Re-arm the per-boot auto-open** (next session start will open it again):

```bash
rm -f ~/.cache/nervepack/dashboard-open-boot
```

## Served (http) vs static (file://) modes

`engine/setup/np-dashboard-launch.sh` (`np_dashboard_url`) picks the URL from the
`evaluator.dashboard_serve` param:

- **`on` (default)** — starts the localhost-only backend `np-dashboard-server.py` on
  `127.0.0.1:<port>` and returns the `http://` URL. The dashboard's action buttons
  (resolve / review / clear suggestions) only work in this mode. The server is
  CSRF-guarded, path-sanitized, route-allowlisted, loopback-bound — see
  [[np-kb-coding-rules]] §10 and the served-mode flow in
  [[np-core-suggestions-review]].
- **`off`** — returns the static `file://…/dashboard/index.html` URL: charts render,
  but the action buttons are inert (no backend). Fail-open: if the server can't start,
  the launcher falls back to `file://` automatically.

## Toggles (params on the `evaluator` family, declared in `engine/setup/toggles.conf`)

| Param | Default | Effect | Flip |
|---|---|---|---|
| `dashboard_open` | `on` | auto-open on the first session of each boot | `nervepack-toggle evaluator.dashboard_open off` |
| `dashboard_serve` | `on` | http backend (buttons work) vs static file:// | `nervepack-toggle evaluator.dashboard_serve off` |
| `dashboard_port` | `8787` | port for the localhost backend | `nervepack-toggle param evaluator.dashboard_port <n>` |

`nervepack-toggle evaluator.<param> off` writes a **per-machine** override
(`~/.config/nervepack/toggles.local`); `nervepack-toggle param evaluator.<param> <v>`
edits the committed manifest (repo-wide default). Both are read by `np_param`, local
first. See [[np-core-toggle]].

## Related

- [[np-core-suggestions-review]] — triage the suggestions panel (served mode powers its buttons)
- [[np-kb-claude-headless-scripting]] §4 — why GUI side-effects are guarded once-per-boot
- [[np-kb-coding-rules]] §10 — locking down the localhost server
