# Verify failure and rollback

A failed live check means diagnose with the deploy output and the live
response, never retry silently, then fix forward or roll back and say which.

To roll back, use the repo's procedure or revert the merge commit, redeploy,
and pass the same live check.
