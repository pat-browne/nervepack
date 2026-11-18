# Parallel run lessons

From a 2026-11-12 run: seven parallel Sonnet streams and one top-tier review.
Each rule names the cost it avoids.

## Before dispatch

1. **Prep once.** Provision the test env for fresh worktrees, such as a venv.
   Prove the gate is green on the default branch. Fix or quarantine flaky tests.
   Otherwise every worker rediscovers the same failures.

2. **Build the measurement first.** When the work has a score, such as a replay
   or a benchmark, land it and its fixtures before the change streams. A stream
   is accepted when the score falls on no fixture and its own target is met.
   Unmeasured flags shipped in this run and later proved harmful.

   The replay fixtures came after the flags were built. They showed blind
   tiling cut four rides' scores by up to 0.40, before any flag shipped on.

## During the run

3. **Review each stream cheaply.** A Haiku reviewer gets the diff and the goal
   before integration. Keep the top-tier review for the integrated whole. One
   late review cost a full fix round.

4. **Tier mechanical workers too.** Merges, flag flips, CI reads and branch
   cleanup go to Haiku.

5. **Gate locally before CI.** Run the full local suite and a local diff
   review before the first push. Push once per round, never once per fix.
   Open the PR as a draft, since a draft runs no CI. Mark it ready only after
   the local gate and review pass.

   For platform code, add a local test that simulates the other platform.
   One example is a patched-out `pwd` module for Windows.

6. **Use a fresh worker per fix round.** Every round's tool output stays in the
   worker's context. Each turn then runs slower and costs more. Older
   instructions also get less attention.

## Verifying workers

7. **Check every claim that changes shared state.** After a reported push, run
   `git ls-remote` and compare the SHA. A worker reported a push that never landed.

8. **Require the red run.** Each report shows the failing test run before the
   fix, or the coordinator ledgers the exception.

9. **A bot-token push starts no workflows.** GitHub skips workflows for events
   made with the default GITHUB_TOKEN, to stop recursive runs. You meet it when
   a bot or responder workflow pushes the PR head. Re-trigger with a push from
   a real identity, such as an empty commit, or re-run from the Actions UI.

## Landing: the home-made merge gate

10. **No merge queue here.** GitHub's docs say: "Pull request merge queues
    are available in any public repository owned by an organization, or in
    private repositories owned by organizations using GitHub Enterprise Cloud."
    Both repos belong to a user account, so build the gate by hand.

11. **Use this order.** Rebase onto the base locally and run the local gate.
    In nervepack, run `cli.py merge-wait` before the push. Open a draft PR.
    Mark it ready to run the fast required checks. Add the `merge-ready` label
    to run the heavy tier once. Merge on green.

12. **Keep the heavy tier off the ready path.** Required checks stay in the
    fast workflow. Heavy jobs live in their own workflow, triggered by the
    `merge-ready` label and by pushes to the default branch. A label trigger
    on the fast workflow would rerun every required job.

13. **Batch, and skip "require up to date".** Land several ready branches
    through one integration branch, so the heavy tier runs once per batch.
    Do not require branches to be up to date. It reruns CI whenever the base
    moves. Rebase locally before marking ready instead.
