# Worker models: parallelism and verification

Continues § Worker models in SKILL.md. Rules for [[np-flow-speed]] and
[[np-core-dispatch]] coordinators apply here too.

- Run independent work in parallel. Dispatch every worker whose task needs no
  other worker's result in one batch.
- Confirm or correct every worker result before it lands. A report is a claim.
  Rerun its tests and its numbers from the worker's branch. Read the diff
  against the goal. Spot-check the evidence behind each finding.
- Form your own theory first. Before a diagnosis worker reports, read the raw
  evidence and write your root-cause theory and one prediction that would
  refute it. Keep it out of the brief, so the worker is not anchored. Compare
  the two when the report lands, and settle any gap with a test.
- Send a wrong finding or a wrong change back to its worker with the evidence.
  A second failure follows the step-up rule in [[np-flow-speed]].
- Log each correction in the decisions log: the claim, the evidence and the
  fix.
