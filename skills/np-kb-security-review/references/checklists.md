# Security-review per-domain checklists

The recurring, high-miss checks. Consult the section matching the surface the diff
touches. Distilled from repeated source-to-sink audits.

## XSS / DOM

- Identify the escaping function (e.g. one covering `& < > "`) and verify it covers
  **every sink context** it's used in. An escaper built for one context (HTML text)
  is not automatically correct for another (attribute, URL, JS, double-quoted YAML).
- Hunt for **new fields** routed to a sink that bypass the escaper, and new sinks
  added without escaping.
- In HAST/rehype/build-time AST plugins: text nodes **auto-escape** on serialization
  (safe by default). `dangerouslySetInnerHTML` and `type:'raw'` nodes are **unsafe** —
  identify which variant each sink uses, and confirm the source is author-controlled
  (markdown), not end-user input, to establish the trust boundary.

## Credential-handling shell scripts

- `umask 077` must precede any sensitive-file write (don't trust tool defaults).
- **Env vs argv for secrets:** env vars are visible in `/proc/PID/environ` (same-user);
  argv is world-readable in `/proc/PID/cmdline`. Passing a secret as a CLI argument
  (e.g. `aws configure set` argv form) is a known leak class — prefer env or stdin.
- Follow sensitive writes with explicit `chmod 600` + a `stat` verification rather
  than assuming the umask held.
- Trace every operator input (CLI args, env, config) through its quoting/escaping
  (`printf '%q'`, `sed` alnum-only, `jq --arg/--argjson`) to each sink (`exec`, JSON
  field, file path). If all sinks are quoted/escaped, no injection gap exists.

## Browser-exposed metrics / dashboard JS

`window.*` globals (and anything serialized into client JS) must **exclude**: session
IDs/UUIDs, project names, infrastructure/host names, skill/hook names, and token/cost
metrics — anything enabling reconnaissance of internal architecture or failure modes.

## YAML / template injection & SSRF

- Verify the escaper matches the **actual** YAML/template context (a helper for
  single-quoted scalars is wrong for double-quoted flow-style where `\` is the escape
  char). Existing escaper ≠ correct for a new sink context.
- **SSRF:** a hardcoded `localhost`/`127.0.0.1` target prevents SSRF; a target derived
  from input needs validation. Unauthenticated LAN TCP is a LAN-trust tradeoff —
  document it; it's not remotely exploitable unless the surface is internet-reachable.

## Archive extraction

Modern `tar -xf` and `unzip` refuse `..` path traversal by default. Flag only
hand-rolled extraction or `--absolute-names`/`-P`-style overrides.

## Config-only / constant-swap changes

When a change is purely a numeric/string value update with **no** new functions,
subprocess calls, branching, or validators:

- Map the value through its consumption path. If it flows into an internal function
  as a plain parameter with no new branching, it's low-risk.
- For a constant swap (model tag, version, path) feeding tools: check the sinks are
  **identical** between old and new, the variable's origin (env/args/file) is
  unchanged, and no validator/allowlist/authz gate was removed. Identical sinks +
  same origin = no new taint surface. An env-var or user-input substitution still
  requires full taint tracing.

## Structured multi-phase pass (large/multi-file reviews)

1. Identify all sinks (shell, SQL, eval, templates, logs, IaC, permissions).
2. Trace sources through trust boundaries; verify escaping/validation. Check for
   parser/logic regressions.
3. Hunt high-miss patterns: observability side-channels, removed validators, missing
   resource caps, fail-open behaviors.
4. Assess. Map source control **before** concluding safety — eliminates false
   negatives while avoiding false positives.
