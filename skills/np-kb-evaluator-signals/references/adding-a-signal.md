# Adding a new signal

1. Add an extractor function to `np-eval-signals.py` following the fail-open pattern (empty/zero default; never raise).
2. Add the field to the `record` dict in `main()`.
3. Update the record shape comment in `docs/ARCHITECTURE.md` (§ "The two data pipelines").
4. Add a test in `setup/tests/evaluator/test_signals.py` (black-box subprocess test).
5. If the signal requires a new runtime marker, write it from the relevant hook via `np_signal "$sid" "<prefix>"` and add a counter branch in `count_markers()`.
