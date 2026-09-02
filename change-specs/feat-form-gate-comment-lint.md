---
id: 0024
status: proposed
date: 2026-09-02
tier: high
blast_radius:
  - engine/nervepack_engine/np_comment_extract.py
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/setup/toggles.conf
  - docs/ARCHITECTURE.md
  - engine/setup/tests/nervepack_engine/test_np_comment_extract.py
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - change-specs/feat-form-gate-comment-lint.md
---

# 0024: form_gate lints code comments too

## Context and problem statement

`form_gate` (spec 0021, then 0023's `block` mode) already lints every
persisted prose surface it can find. A source file's own comments and
docstrings pass through untouched. `_prose_ext` deliberately keeps
`.py`/`.ts`/etc. out of scope, because the linter's regexes assume prose, not
code.

A maintainer who wants the same categorical rules (no em dash, no marketing
adjective, the two length rules) to hold in comment prose, not only in
Markdown and Slack messages, has no way to reach it today.

## Considered options

1. **Lint the whole file, code included.** Rejected. The linter's regexes are
   built for prose. Running them over code and string literals produces
   overwhelming noise, and would train a maintainer to ignore the gate.

2. **A full language-aware parser per supported extension.** Rejected as
   disproportionate. Nervepack is stdlib-only by policy (AGENTS.md "Harness
   language policy"), and a real parser for six-plus languages is a
   maintenance burden this feature does not need. A conservative line scanner
   gets most of the value at a fraction of the risk surface.

3. **A conservative, per-language comment/docstring extractor, opt-in via a
   new `comment_ext` toggle, feeding the same linter and, in `block` mode,
   the same deny/retry/escalate machine 0023 already built.** Chosen. It
   reuses every existing mechanism (the linter subprocess, the categorical/
   rate channels, the retry counter, the escalation struggle) and adds
   exactly one new piece of state: the extractor itself, which is pure
   text-in/text-out and easy to test in isolation.

## Decision

`engine/nervepack_engine/np_comment_extract.py` is a new, stdlib-only module.
Its entry point is `extract_comments(text, ext) -> (comment_text,
max_block_lines)`. Extraction is per language and line-oriented.

Python (`.py`): `#` line comments, both whole-line and trailing, skipped
inside string literals. A triple-quoted string counts as a docstring only
when it opens as the first statement of the module, or immediately follows a
`def`/`class` line ending in `:`. Any other triple-quoted string is left
alone, under-extracting rather than linting arbitrary string data.

C-like (`.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.go`, `.rs`, `.java`,
`.c`, `.h`, `.cpp`, `.cc`): `//` and `/* ... */`. Both are skipped inside
string and template literals, and a `//` that is really `https://` is
skipped too.

Shell (`.sh`, `.bash`, `.zsh`): `#`, skipped inside quotes. SQL (`.sql`):
`--`, skipped inside quotes.

A contiguous comment block is a run of consecutive comment lines with no
code line between them. A `/* */` block counts by its own line span even
when code shares its opening or closing line. `max_block_lines` reports the
longest such block. The function never raises. Any parse difficulty returns
whatever was extracted so far.

`form_gate.py` gains two params, read the same way `prose_ext` already is.
`comment_ext` defaults to empty, so the feature ships inert. A maintainer
lists extensions to scope in, e.g. `.py,.ts`. `comment_block_max` defaults
to 20.

`_is_comment_path` matches a path against `comment_ext` and explicitly
excludes anything `_is_prose_path` already claims, so a prose file never
picks up the comment-lint path. `_extract`'s Write/Edit branch checks
`_is_comment_path` first. A match runs `np_comment_extract.extract_comments`
over the same content Write/Edit already lint (the added text for Write,
`new_string` for Edit) and returns `(comment_text, basename)`, or `(None,
"")` when no comment text was found. Everything downstream, categorical hits
and the rate channel alike, runs unchanged over that returned text.

The length ceiling only fires in `block` mode, the one place 0023 built a
deny/retry/escalate machine for it to ride. `run()` computes
`_comment_max_block`, which is 0 for anything that is not a comment-scoped
Write/Edit, including every prose file. When that value exceeds
`comment_block_max`, `run()` merges a synthetic `long_comment_block`
violation into the `violations` dict before calling `_run_block`, with a
dynamic label carrying the actual threshold. `_BLOCKING` and `_RULE_LABEL`
gain the new key. `_blocking_hits`/`_run_block` take an optional
`extra_labels` override, so the threshold-carrying label does not have to be
a compile-time constant.

## Non-goals

- Making the feature on by default. `comment_ext` ships empty, a maintainer
  opts a scope in, the same way `categorical=block` itself is opt-in.

- A real parser. The extractor is a conservative scanner, not a compiler
  front end, and is documented as such.

- Touching the linter (`np-ste-lint.py`) or the categorical/rate machinery.
  This change only supplies it different input text, and, in `block` mode,
  one new synthetic key.

- Extending comment-lint to any surface besides Write/Edit on a source path.
  Artifacts, MCP sends, and commit messages already have their own
  extraction paths and are untouched.

## Cross-cutting concerns

- Security: the extractor is pure text-in/text-out, stdlib-only, with no
  subprocess and no file I/O of its own. No new secret-bearing state exists.

- Privacy: nothing new is written to disk. The extracted comment text is
  piped straight into the existing linter subprocess call, the same path
  prose text already takes.

- Observability: a `block`-mode deny or escalation on `long_comment_block`
  signals and records a struggle through the exact same calls 0023 wired for
  every other blocking rule.

## Consequences

- Good, because a maintainer who wants the categorical rules to hold in
  source-file comments now has a scoped, opt-in way to get there, reusing
  every mechanism 0021 and 0023 already built.

- Good, because the extractor is a pure function, independently testable
  without any of `form_gate`'s toggle or subprocess machinery.

- Neutral, because a forker who never sets `comment_ext` sees no behavior
  change at all. The default is empty.

- Bad, because the extractor is one more piece of per-language logic to keep
  correct as new languages get requested. Mitigated by keeping it
  deliberately conservative, under-extracting on ambiguity rather than
  trying to be exhaustive.

## Confirmation

`engine/setup/tests/nervepack_engine/test_np_comment_extract.py` covers
per-language extraction. This includes a `#`/leading-docstring Python case
and its negative (a non-docstring triple-quoted string is not extracted), a
`//`/`/* */` C-like case including the `https://`-in-a-string negative case,
a shell/SQL case, and `max_block_lines` correctness for a multi-line block.

`engine/setup/tests/nervepack_engine/test_form_gate.py` is extended.
With `comment_ext` set to `.py`, a source file whose comment carries a
marketing adjective blocks. Clean code passes. A comment block over
`comment_block_max` blocks with the "long comment block" label. With
`comment_ext` empty, the default, a `.py` write is not gated at all. The
prose-file path is unchanged and never picks up `long_comment_block`.

`bash engine/setup/tests/run-all.sh` passes, aside from the pre-existing,
unrelated `test_dashboard_lifecycle.py` failure already present on `main`.

## Rollback

To disable without reverting code, in `~/.config/nervepack/toggles.local`,
set:

```
form_gate.comment_ext=
```

This is already the shipped default, so it is only needed to undo a
maintainer's own opt-in. To turn off the whole hook instead, set:

```
form_gate=off
```

To revert the code, `git revert` the merge commit. No hook registration
change is needed. `form_gate` is already registered on its six PreToolUse
matchers.

## Deviations

(none yet)
