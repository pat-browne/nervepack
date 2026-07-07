---
name: np-kb-campminder-azure
description: Campminder Azure infrastructure conventions — required resource tags (Phase 1), allowed values, where to apply them, and the Terragrunt common.hcl pattern. Use when deploying any Azure resource, writing or reviewing Terraform/Terragrunt for Campminder, or verifying a deployment meets tagging requirements.
---

# Campminder Azure infrastructure conventions

## Required tags (Phase 1 — enforced)

All Azure resources and resource groups must carry these three tags.
Enforcement: **Azure Policy (deny effect)** at resource creation + **Terraform
`validation` blocks** in the registry modules.

**Naming convention:** all lowercase, kebab-case — no spaces, no special characters.

| Tag key | Allowed values |
|---|---|
| `environment` | `dev` `qa` `prod` `unknown` |
| `app` | See app values below |
| `managed-by` | See team values below |

### `app` values

`core-monolith`, `core-legacy`, `camp-erp`, `campanion`, `campanion-admin`,
`gazebo`, `data`, `infra`, `ce`, `srm`, `payments`, `lcn`, `people`,
`registration`, `campos`, `eac`, `airflow`

- `infra` — cross-cutting: networking, security, shared DBs (TWinSQL), APIM, monitoring, build/CI
- `core-legacy` = Terragrunt workload name for modernised core-monolith; treat as synonym for `core-monolith` in reports
- `payments` pairs with `managed-by = team-unknown` (project inactive)

### `managed-by` values

`team-alpha`, `team-apollo`, `team-phoenix`, `team-delta`, `team-data`,
`team-gazebo`, `team-platform`, `team-shared`, `team-unknown`

- `team-shared` — genuinely multi-tenant resources (QA IIS boxes, AKS clusters hosting multiple teams)
- `team-platform` — **reserved** for resources platform team built/runs as their own work (VPN, network watcher, build infra). Not a catch-all for shared infra.
- `team-unknown` — no current owner (dead/inactive projects)

### `environment` notes

- Use `unknown` only for auto-created or cross-env platform resources (e.g. `NetworkWatcherRG`, Defender defaults)
- **Never use `unknown` in prod** — prod resources always tag `prod`

## Where to apply tags

| Resource type | Apply at |
|---|---|
| Modern PaaS (App Services, Functions, AKS, Cosmos, Service Bus, Storage) | **Resource group level** |
| Legacy Azure resources | **Resource level directly** |
| Shared/platform infra | Resource group level; `app = infra` + `managed-by = team-shared` or `team-platform` |

## Terraform / Terragrunt pattern

Tags are set **once per environment** in `ci/live/<env>/common.hcl` and flow to
every module via `var.tags`. Registry modules **v3.30.0+** propagate tags to all
sub-resources (private endpoints, managed identities, function storage accounts,
managed certs — fixed by ADO #19745).

```hcl
# ci/live/prod/common.hcl
inputs = {
  tags = {
    app         = "data"
    managed-by  = "team-data"
    environment = "prod"
  }
  # ...
}
```

Do **not** set tags per `terragrunt.hcl`. Always inherit from `common.hcl`.

## Kubernetes / Helm (AKS workloads)

AKS workloads (e.g. data-team-mcp) run inside a shared cluster tagged at the
resource group level. The Helm chart does not set Azure tags — cost attribution
depends on the containing resource group carrying the correct tags.

## Special cases

```
# Shared multi-tenant infra
app = infra   managed-by = team-shared

# Platform-owned infra (VPN, build agents)
app = infra   managed-by = team-platform

# Inactive / orphaned (Payments)
app = payments   managed-by = team-unknown
```

Untaggable resources (some auto-created RGs): document in Terraform comments,
use `environment = unknown`.

## Phase 2 (reserved — not yet in use)

`cost-center` — finance-grade chargeback, splits operator vs payer.
`provisioned-by` — `terraform` or `manual`, for drift detection.

## References

- [Notion TDR — authoritative](https://app.notion.com/p/34fd23fa124b8048bc24d1ab81409eb6) (authored by Ben Kutsch, May 2026, Status: In Review)
- [ADO wiki page](https://dev.azure.com/CampMinderLLC/925e2411-7837-4923-bb74-c2ae3b6b8130/_wiki/wikis/71898342-1b6b-47d0-99d1-a94837eef635?pagePath=%2FAzure-Resource-Tagging-Standards)
- ADO work items: #17938 (spike), #17941 (implement), #19745 (sub-resource propagation)
- Existing tag coverage as of 2026-06-04: ~59% (tracked in silver layer, ADO #18842)

## Known drift

The `sql-dba` repo uses the **old** tag schema (`Environment` / `Vertical` in
Title Case) — migrate to lowercase Phase 1 schema when next touched.
