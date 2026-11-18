# Worker brief checklist

Add these to every brief for a repo-editing worker.

- **Format only touched files.** Name the files. A repo-wide formatter run once
  touched 337 files.
- **Set up the env.** A fresh worktree has no venv or installed deps. Name the
  step that provisions them, such as the repo's setup script.
- **Report red then green.** The report shows the failing test run before the
  fix and the passing run after. A missing red run needs a stated reason.
- **Confirm every push.** After pushing, run `git ls-remote origin <branch>` and
  report the SHA. A reported push has failed to land before.
