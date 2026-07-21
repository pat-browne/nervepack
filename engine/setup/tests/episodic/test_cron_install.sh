#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../70-install-memory-cron.sh"

# Sandbox crontab: shim a fake `crontab` backed by a temp file, on PATH.
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
touch "$tmp/crontab.txt"
cat > "$tmp/crontab" <<SHIM
#!/usr/bin/env bash
if [[ "\${1:-}" == "-l" ]]; then cat "$tmp/crontab.txt"; exit 0; fi
cat > "$tmp/crontab.txt"
SHIM
chmod +x "$tmp/crontab"

PATH="$tmp:$PATH" bash "$INSTALL" >/dev/null
PATH="$tmp:$PATH" bash "$INSTALL" >/dev/null   # idempotent second run

grep -q 'nervepack-memory-promote'   "$tmp/crontab.txt" || { echo "FAIL: memory cron line missing"; exit 1; }
grep -q 'nervepack-episodic-maintain' "$tmp/crontab.txt" || { echo "FAIL: episodic cron line missing"; exit 1; }
[[ "$(grep -c 'nervepack-episodic-maintain' "$tmp/crontab.txt")" == "1" ]] || { echo "FAIL: episodic line duplicated"; exit 1; }
grep -q '30 8 \* \* \* .*cli.py cron episodic-maintain' "$tmp/crontab.txt" || { echo "FAIL: episodic schedule wrong"; exit 1; }
echo "PASS test_cron_install"
