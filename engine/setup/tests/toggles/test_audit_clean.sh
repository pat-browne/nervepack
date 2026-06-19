#!/usr/bin/env bash
# np-test: toggle-audit | failure
# Failure path for nervepack-toggle-audit.sh: a CLEAN install (every nervepack
# hook/cron command maps to a toggle family present in toggles.conf) must report
# ZERO gaps — no UNMANAGED lines, and the explicit "OK: all ... map" summary. The
# existing test_audit.sh only exercises the flagged (drift) path; this asserts the
# complementary all-managed outcome so a regression that spuriously flags managed
# hooks is caught.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT="$HERE/../../nervepack-toggle-audit.sh"
command -v jq >/dev/null || { echo "PASS test_audit_clean (skipped — jq missing)"; exit 0; }
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" CLAUDE_SETTINGS="$tmp/settings.json"

# Hermetic crontab: the audit reads `crontab -l`; shim it to an empty crontab so
# the test never inspects (or depends on) the dev box's real cron entries.
cat > "$tmp/crontab" <<'SHIM'
#!/usr/bin/env bash
[[ "${1:-}" == "-l" ]] && exit 0
cat >/dev/null
SHIM
chmod +x "$tmp/crontab"
export PATH="$tmp:$PATH"

# Every family the audit's MAP can require must be declared here.
cat > "$tmp/toggles.conf" <<'C'
memory|shared|runtime|on|
playbooks|shared|runtime|on|
evaluator|shared|runtime|on|
directive|shared|runtime|on|
sync|shared|runtime|on|
C

# Settings whose hooks are ALL recognised nervepack scripts that map to a declared
# family (memory + playbooks + directive), plus an installer that the audit must
# deliberately ignore (60-generate-index.sh) — so a clean install really is clean.
jq -n '{hooks:{
  SessionStart:[{matcher:"",hooks:[{type:"command",command:"~/Code/nervepack/engine/setup/nervepack-session-directive.sh"}]}],
  UserPromptSubmit:[{matcher:"",hooks:[{type:"command",command:"~/Code/nervepack/engine/setup/episodic-recall.sh"}]}],
  PreToolUse:[{matcher:"Bash",hooks:[{type:"command",command:"~/Code/nervepack/engine/setup/playbook-guard.sh"}]},
              {matcher:"",hooks:[{type:"command",command:"~/Code/nervepack/engine/setup/60-generate-index.sh"}]}]
}}' > "$CLAUDE_SETTINGS"

rc=0; out="$(bash "$AUDIT" 2>&1)" || rc=$?
[[ "$rc" == 0 ]] || { echo "FAIL: audit exited $rc on a clean install: $out"; exit 1; }
echo "$out" | grep -q 'UNMANAGED' && { echo "FAIL: clean install reported UNMANAGED: $out"; exit 1; }
echo "$out" | grep -q 'OK: all Nervepack hooks/cron map to a toggle family' \
  || { echo "FAIL: missing the clean-install OK summary: $out"; exit 1; }
echo "PASS test_audit_clean"
