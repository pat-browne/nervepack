# Layout interview — worked example and manifest shape

Depth for [[np-core-layout]]. Read when running the interview or hand-editing a
manifest.

## Manifest fields

| Field | Meaning |
|---|---|
| `schema` | Always `1`. A different value is rejected. |
| `routes` | Kind to path template. A template uses `{name}` and `{topic}`. |
| `routes.<kind>.variants` | Present when one kind splits. Each carries a `when` rule. |
| `routes.<kind>.frontmatter` | Fields stamped on a new page of this kind. |
| `routes.<kind>.append` | `true` when writes append to one file (a roadmap). |
| `index` | The index file discovery reads. Usually `INDEX.md`. |
| `links` | `wikilink` or `path`. Picks the inbound-link style. |
| `derived_from` | Prose docs the routes came from. Re-read them to detect drift. |
| `unmapped` | Directories that are not contribution targets. Stops repeat questions. |

Full shape:

```json
{
  "schema": 1,
  "derived_from": ["README.md", "wiki/README.md"],
  "routes": {
    "skill":     {"path": "skills/{name}/SKILL.md"},
    "knowledge": {"variants": [
      {"name": "concept", "when": "source-free synthesis of one entity or idea",
       "path": "wiki/concepts/{topic}/{topic}.md",
       "frontmatter": {"kind": "concept"}},
      {"name": "topic", "when": "synthesis that owns curated reference sources",
       "path": "wiki/topics/{topic}/{topic}.md",
       "frontmatter": {"kind": "topic"}}
    ]},
    "reference": {"path": "wiki/topics/{topic}/{name}.md",
                  "frontmatter": {"kind": "reference"}},
    "roadmap":   {"path": "ROADMAP.md", "append": true},
    "prompt":    {"path": "agents/{name}.md"}
  },
  "index": "INDEX.md",
  "links": "wikilink",
  "unmapped": ["brand/", "tools/", "scripts/"]
}
```

## Worked interview

A layer holds `skills/`, `notes/`, `refs/`, and `brand/`. No page carries
frontmatter, so inference finds only the skill route.

```
$ cli.py layout questions --layer personal
[{"id": "missing-kind:knowledge", ...},
 {"id": "missing-kind:roadmap", ...},
 {"id": "unmapped-dir:notes", "evidence": "contains markdown: notes/a.md"},
 {"id": "unmapped-dir:refs", ...},
 {"id": "unmapped-dir:brand", ...}]
```

Five questions. Read `derived_from` first. The layer's `README.md` says:

> `notes/` holds my own write-ups. `refs/` holds vendor docs I did not write.

That prose settles three questions before you ask anything. Record:

```json
"knowledge": {"path": "notes/{name}.md"},
"reference": {"path": "refs/{name}.md"}
```

Re-run `layout questions`. Two survive: `missing-kind:roadmap` and
`unmapped-dir:brand`. Ask **one**:

> What does `brand/` hold, and should contributions ever land there?

Answer: "Logos and color tokens. Never a contribution target." Apply it:

```json
"unmapped": ["brand/"]
```

Re-run. One survives. Ask it. Answer: "Deferred work goes in `ROADMAP.md`." Apply,
re-run, the list is empty, and the interview ends. Five questions became two asked,
because prose answered three and the list was re-evaluated after every answer.

## Answer to route

| The user says | You record |
|---|---|
| "X lives in `dir/`, one file per page" | `"X": {"path": "dir/{name}.md"}` |
| "X lives in `dir/<topic>/<topic>.md`" | `"X": {"path": "dir/{topic}/{topic}.md"}` |
| "X sits beside the page that owns its folder" | `"X": {"path": "dir/{topic}/{name}.md"}` |
| "X splits into A and B, by <rule>" | a `variants` list, one entry per split, each with `when` |
| "`dir/` is not for contributions" | append `"dir/"` to `unmapped` |
| "everything appends to one file" | `"X": {"path": "FILE.md", "append": true}` |

## When prose and disk disagree

Inference reports what pages actually do; prose reports what someone once intended.
Trust the disk and tell the user. A real case: an overlay's `wiki/README.md`
documented concepts as flat `wiki/concepts/<name>.md`, while all eight concept pages
were folder-owning `wiki/concepts/<name>/<name>.md`. The manifest recorded the real
shape, and the stale sentence became a separate doc fix.

## Read-only layers

A vendored or read-only team layer cannot take the manifest. `record()` falls back
to `~/.config/nervepack/layouts/<base>-<hash>.json`, and `load()` reads it back, so
the layer behaves the same and only the file location differs. Prefer a PR to the
team repo, so every member inherits the same routes.

## What the engine refuses

`route()` raises rather than returning a path when:

- an interpolated value is not one safe segment (`[A-Za-z0-9._-]`, not `.` or `..`),
- a template is absolute,
- the resolved path leaves the layer root, symlinks included.

A manifest arrives inside a repo, and a team overlay syncs from a remote other
people write to, so these are enforced in the resolver, never in the callers.
