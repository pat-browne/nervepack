# Deploy gates under an orchestrator

The post-deploy loop lives in np-flow-develop. These rules cover the gate itself.

- Per gate, a validator reads the full plan and returns APPROVE or REJECT. An adversarial critic then reviews any APPROVE.
- Before reporting a gate, list queued runs for the pipeline. Flag any extra run.
- Freeze worker pushes on that branch while a gate is open. Lift it after the environment validates.
- Approve the infra gate before the bundle or app gate.
- A trunk fix needed by an in-flight branch is cherry-picked onto that branch. Never deploy a trunk branch over it.
- Job proof: run affected jobs in dev and qa. In prod, only an observed scheduled run counts.
