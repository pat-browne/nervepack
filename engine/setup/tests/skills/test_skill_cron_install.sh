#!/usr/bin/env bash
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

bash "$INSTALLER" >/dev/null
bash "$INSTALLER" >/dev/null   # run twice — must stay idempotent
n=$(grep -c 'nervepack-skill-maintain' "$store" || true)
[[ "$n" == "1" ]] || { echo "FAIL: expected 1 skill-maintain entry, got $n"; exit 1; }
grep -q '15 9 \* \* \* .*cli\.py cron skill-maintain # nervepack-skill-maintain' "$store" \
  || { echo "FAIL: cron line wrong: $(grep skill-maintain "$store")"; exit 1; }
echo "PASS test_skill_cron_install"
