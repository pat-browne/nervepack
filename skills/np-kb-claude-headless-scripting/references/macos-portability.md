# macOS/BSD Portability Patterns for nervepack Scripts

Runtime hook/cron scripts ship unported on any adopting nervepack host. GNU-only
constructs that work on the Ubuntu dev box silently break on macOS (BSD coreutils,
default bash 3.2). The numbered `NN-*.sh` bootstrappers are exempt — they are
Linux/apt-only by design.

## GNU-only constructs to avoid and portable alternatives

- **`stat -c %s` / `stat -c %Y`** (GNU) — BSD `stat` uses `-f` (`%z` size, `%m` mtime).
  For *size*, prefer portable `wc -c < "$f" | tr -d '[:space:]'`. For *mtime*, use a
  try-GNU-then-BSD helper: `np_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }`.
- **`find … -printf`** (GNU-only) — BSD `find` has no `-printf`. To sort by mtime, list
  paths with a POSIX `find` (`-name`/`-type`/`-mtime` are fine) then prefix mtime in a
  loop: `find … | while read -r p; do printf '%s %s\n' "$(np_mtime "$p")" "$p"; done | sort -rn | cut -d' ' -f2-`.
- Other GNU-isms to avoid in runtime scripts: `readlink -f`, `grep -P`,
  `date -d`/`--date`, `sed -i` (BSD needs a backup-suffix arg), `${var,,}` and
  `declare -A` (bash 4+; macOS ships 3.2).

## Enforcement

`engine/setup/tests/meta/test_macos_portability.sh` scans every non-bootstrap runtime
script for these patterns (exempting comments and the deliberate `stat -c … || stat -f`
fallback). Add new runtime scripts to the same standard.
