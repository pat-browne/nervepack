# Auditing signal health

To check whether a session's signals are real or structural zeros:

```bash
# 1. Does the signal log exist for this session?
ls ~/.cache/nervepack/session-signals/<sid>.log

# 2. Does the episodic inbox have a record for this session?
grep '"session_id":"<sid>"' ~/.cache/nervepack/episodic-inbox/*.jsonl

# 3. Was this session back-captured (never had a live signal log)?
# Back-captured records will have recall_injections=0 regardless of hooks fired.
# Check whether ts in metrics.jsonl predates the signals infrastructure being installed.
```
