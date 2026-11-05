# Decisions log template

```text
Decisions
1. <decision> -- <one-line reason>
2. <decision> -- <one-line reason> (deferred to coordinator)
3. <worker> on <model> -- <task>
4. <worker> step-up <from> to <to> -- <failure that caused it>

Stopped at limits
- <action> -- <which limit> -- <your recommendation>

Captured
- <fact> -> <skill, reference or wiki path>

Scope suggestions
- <idea> -- <how it helps the end goal>
```

The final report also gives the PR link, merge state, CI result, the worker
and step-up lines from the log, and status per environment.
