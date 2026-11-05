# Deploy gates under an orchestrator

A gate is a manual approval job in a deploy pipeline run (ADO environment check
or GitHub environment review). The post-deploy validation loop lives in
[[np-flow-develop]]. These rules cover the approval step itself.

## Validator and critic

- When a Plan job completes, dispatch a validator agent to read the full plan log.
  It returns APPROVE or REJECT with one line per unit. A unit is one Terragrunt
  module directory (or one bundle target) that the job plans and applies on its own.
- Dispatch a separate critic agent to review any APPROVE. It tries to find a
  reason to reject.
- Bring the gate to the user only with APPROVE from both.
- If an agent times out, errors, or the critic disagrees, the gate stays pending.
  Report it to the user as `waiting on me` with the agent's last output. Never
  approve on a partial verdict.
- A gate stuck pending: read the run's timeline (`az pipelines runs show` or
  `gh run view`) for the waiting job and its check, then the validator output.

## Queued runs

- Before reporting a gate, list runs for that pipeline and branch
  (`az pipelines runs list --branch <ref>` or `gh run list --branch <ref>`).
- More than one active run is a flag. Name the extra run id in the gate report
  to the user, and record it in the ledger. Reject it if it planned during the
  apply, since its plan is stale. No alert or webhook fires: the report is the signal.

## Push freeze

- The freeze is a brief rule, not a hook or branch protection. Every worker brief
  says: no pushes while a deploy on your branch is pending or running.
- When a gate opens, send each worker on that branch one message: freeze pushes.
- A worker that must push asks the orchestrator first and waits.
- Lift the freeze by message after the environment validates. Nothing lifts it
  automatically.

## Order and trunk fixes

- Approve the infra gate before the bundle or app gate.
- A fix that lands on trunk while a branch is mid-deploy is cherry-picked onto that
  branch. Never deploy trunk over the in-flight branch's environment.

## Proving jobs after a deploy

- In dev and qa, run the jobs the change touched and check they succeed.
- In prod, a job counts as proven only after a scheduled run succeeds. Never start
  prod jobs to prove a deploy.
