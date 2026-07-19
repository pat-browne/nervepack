#!/usr/bin/env bash
# np-test: maintain-cron-install | idempotency
# 70-install-memory-cron.sh must install nervepack-refine and nervepack-compact
# idempotently (two runs → one entry each) and the remove command must delete them.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$HERE/../../70-install-memory-cron.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Fake crontab: store state in a file, mimic `crontab -l` / `crontab -`.
store="$tmp/cron"; : > "$store"
cat > "$tmp/crontab" <<STUB
#!/usr/bin/env bash
if [[ "\${1:-}" == "-l" ]]; then cat "$store"; else cat > "$store"; fi
STUB
chmod +x "$tmp/crontab"
export PATH="$tmp:$PATH"

# Run twice — must stay idempotent.
bash "$INSTALLER" >/dev/null
bash "$INSTALLER" >/dev/null

# Both entries must exist exactly once.
n_refine=$(grep -c 'nervepack-refine' "$store" || true)
n_compact=$(grep -c 'nervepack-compact' "$store" || true)
[[ "$n_refine" == "1" ]] || { echo "FAIL: expected 1 nervepack-refine entry, got $n_refine"; exit 1; }
[[ "$n_compact" == "1" ]] || { echo "FAIL: expected 1 nervepack-compact entry, got $n_compact"; exit 1; }

# Check the schedule and script references.
grep -q '30 9 \* \* 0 .*cli\.py cron refine # nervepack-refine' "$store" \
  || { echo "FAIL: refine cron line wrong: $(grep refine "$store" || true)"; exit 1; }
grep -q '0 10 \* \* 3 .*77-run-compact\.sh # nervepack-compact' "$store" \
  || { echo "FAIL: compact cron line wrong: $(grep compact "$store" || true)"; exit 1; }

# Simulate the documented remove command and verify entries are gone.
grep -vF 'nervepack-refine' "$store" | grep -vF 'nervepack-compact' > "$tmp/cron-after-remove"
grep -q 'nervepack-refine' "$tmp/cron-after-remove" && { echo "FAIL: refine entry not removed"; exit 1; }
grep -q 'nervepack-compact' "$tmp/cron-after-remove" && { echo "FAIL: compact entry not removed"; exit 1; }

echo "PASS test_install_idempotency"
