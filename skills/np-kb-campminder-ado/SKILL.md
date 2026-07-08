---
name: np-kb-campminder-ado
description: Campminder ADO (Azure DevOps) operational patterns — MCP plugin capabilities and gaps, az repos CLI fallbacks, CI pipeline IDs. Use when completing/merging PRs, queueing CI builds, or diagnosing why an ADO MCP tool call failed on the Campminder data-catalog or sibling repos.
---

# Campminder ADO operational patterns

## Key identifiers

| Thing | Value |
|---|---|
| ADO org | `https://dev.azure.com/CampMinderLLC/` |
| ADO project | `CampMinder` (old capitalization — used in ADO; new spelling is `Campminder`) |
| data-catalog repo ID | `data-catalog` |
| data-catalog CI pipeline | definition ID `389`, name `data-catalog-ci` |

## MCP plugin: `plugin:data-base_azure-devops`

The MCP plugin covers most ADO operations. Known gaps:

### `repo_update_pull_request` cannot complete/merge a PR

`status` only accepts `"Active"` or `"Abandoned"` — not `"completed"`. Attempting
`status: "completed"` throws an `invalid_enum_value` error.

**Fallback: `az repos pr update`**

```bash
az repos pr update \
  --id <PR_ID> \
  --status completed \
  --squash true \
  --delete-source-branch true \
  --org https://dev.azure.com/CampMinderLLC/ \
  --detect false
```

- `--detect false` is required — without it the CLI tries to auto-detect the
  project from the CWD git remote, which is the data-catalog ADO remote, not a
  local remote `az` can resolve.
- Command is `az repos pr`, **not** `az devops pr` — the latter fails with
  "misspelled or not recognized".
- The `azure-devops` extension must be installed: `az extension show --name azure-devops`.

### Queueing a CI build

Use `pipelines_run_pipeline` from the MCP plugin — it does work:

```
pipelines_run_pipeline(project="CampMinder", pipelineId=389, branch="refs/heads/<branch>")
```

The ADO pipeline trigger on PRs does **not** auto-fire reliably for manually
created PRs — always queue manually after creating a PR.

## CI jobs (data-catalog-ci, definition 389)

Three parallel jobs — all must pass:

| Job | What it checks |
|---|---|
| `Python (ingest) — ruff, mypy, pytest` | ruff lint, mypy types, pytest |
| `API (app/server) — eslint, tsc, vitest` | eslint, tsc, vitest |
| `Dashboard (app/web) — eslint, tsc, build, vitest` | eslint, tsc, build, vitest |

The `NodeTool@0` deprecation warnings on the Node jobs are pre-existing noise —
not failures.

## Common ruff pitfalls in this repo

- `I001` (import sort): third-party imports in separate blank-line groups get
  flagged. All third-party imports must share one group, separated from stdlib
  above and local imports below.
