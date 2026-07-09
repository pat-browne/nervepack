#!/usr/bin/env bash
# np-test: resume|install
# Task 5: the toggle row, hook installer (61-install-resume-hook.sh), the opt-in
# interval cron (70-install-memory-cron.sh gated on resume.cron), and the writer's
# --active discovery mode (np-resume-write.sh). Hermetic: temp CLAUDE_SETTINGS,
# temp NP_TOGGLES_CONF/LOCAL, a stubbed crontab, and a temp CLAUDE_PROJECTS_DIR —
# never touches real state (~/.claude/settings.json, the real crontab, ~/.cache).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../../../.." && pwd)"   # tests/resume -> setup -> engine -> repo root
INSTALL_HOOK="$NP/engine/setup/61-install-resume-hook.sh"
INSTALL_CRON="$NP/engine/setup/70-install-memory-cron.sh"
TOGGLE="$NP/engine/setup/nervepack-toggle.sh"
WRITER="$NP/engine/setup/np-resume-write.sh"

fail() { echo "FAIL: $*"; exit 1; }

command -v jq >/dev/null || { echo "PASS test_resume_install (skipped — jq missing)"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Hermetic toggle isolation for the whole file: never read the dev box's real
# ~/.config/nervepack/toggles.local.
export NP_TOGGLES_LOCAL="$tmp/toggles-local-none"

# === 1. Hook install: both hooks registered, right event, right basename;
#        SessionStart backgrounded, UserPromptSubmit not; idempotent re-run. ===
export CLAUDE_SETTINGS="$tmp/settings.json"
echo '{}' > "$CLAUDE_SETTINGS"

bash "$INSTALL_HOOK" >/dev/null || fail "install script failed"
bash "$INSTALL_HOOK" >/dev/null || fail "install script failed on second run"   # idempotent

ss_count="$(jq '[.hooks.SessionStart[].hooks[].command] | length' "$CLAUDE_SETTINGS")"
up_count="$(jq '[.hooks.UserPromptSubmit[].hooks[].command] | length' "$CLAUDE_SETTINGS")"
[[ "$ss_count" == "1" ]] || fail "SessionStart count=$ss_count (want 1 — idempotency broken)"
[[ "$up_count" == "1" ]] || fail "UserPromptSubmit count=$up_count (want 1 — idempotency broken)"

jq -e '.hooks.SessionStart[0].hooks[0].command | test("np-resume-sessionstart\\.sh")' "$CLAUDE_SETTINGS" >/dev/null \
  || fail "SessionStart command has the wrong script basename"
jq -e '.hooks.SessionStart[0].hooks[0].command | test(" &$")' "$CLAUDE_SETTINGS" >/dev/null \
  || fail "SessionStart command should be backgrounded with a trailing &"
jq -e '.hooks.UserPromptSubmit[0].hooks[0].command | test("np-resume-recall\\.sh")' "$CLAUDE_SETTINGS" >/dev/null \
  || fail "UserPromptSubmit command has the wrong script basename"
jq -e '.hooks.UserPromptSubmit[0].hooks[0].command | test(" &$") | not' "$CLAUDE_SETTINGS" >/dev/null \
  || fail "UserPromptSubmit command should NOT be backgrounded"

echo "PASS: hook install registers both events with correct backgrounding, idempotent"
unset CLAUDE_SETTINGS

# === 2. nervepack-toggle.sh audit does not flag resume as missing a family ===
export NP_TOGGLES_CONF="$tmp/toggles-audit.conf"
export CLAUDE_SETTINGS="$tmp/settings-audit.json"
cat > "$NP_TOGGLES_CONF" <<'C'
memory|shared|runtime|on|
resume|shared|runtime|on|interval=300,max_age=86400,cron=off,cron_min=5
C
jq -n '{hooks:{
  SessionStart:[{matcher:"",hooks:[{type:"command",command:"~/Code/nervepack/engine/setup/np-resume-sessionstart.sh &"}]}],
  UserPromptSubmit:[{matcher:"",hooks:[{type:"command",command:"~/Code/nervepack/engine/setup/np-resume-recall.sh"}]}]
}}' > "$CLAUDE_SETTINGS"

# Hermetic crontab for the audit's `crontab -l` read — an empty crontab.
cat > "$tmp/crontab" <<'SHIM'
#!/usr/bin/env bash
[[ "${1:-}" == "-l" ]] && exit 0
cat >/dev/null
SHIM
chmod +x "$tmp/crontab"

audit_out="$(PATH="$tmp:$PATH" bash "$TOGGLE" audit 2>&1)"
echo "$audit_out" | grep -qi 'resume' && fail "audit flagged resume as unmanaged: $audit_out"
echo "$audit_out" | grep -q 'OK: all Nervepack hooks/cron map to a toggle family' \
  || fail "audit did not report a clean install: $audit_out"

echo "PASS: toggle audit does not flag resume as missing a family"
unset NP_TOGGLES_CONF CLAUDE_SETTINGS

# === 3. Cron: resume entry present only when resume.cron=on; gated, idempotent,
#        and a flip back to off removes the stale entry. ===
tmp_cron="$tmp/cron.txt"; : > "$tmp_cron"
cat > "$tmp/crontab" <<CRONSHIM
#!/usr/bin/env bash
if [[ "\${1:-}" == "-l" ]]; then cat "$tmp_cron"; else cat > "$tmp_cron"; fi
CRONSHIM
chmod +x "$tmp/crontab"

export NP_TOGGLES_CONF="$tmp/toggles-cron-off.conf"
printf 'resume|shared|runtime|on|interval=300,max_age=86400,cron=off,cron_min=5\n' > "$NP_TOGGLES_CONF"
PATH="$tmp:$PATH" bash "$INSTALL_CRON" >/dev/null
grep -q 'nervepack-resume-cron' "$tmp_cron" && fail "resume cron entry present while resume.cron=off"

echo "PASS: no resume cron entry while cron=off (default)"

export NP_TOGGLES_CONF="$tmp/toggles-cron-on.conf"
printf 'resume|shared|runtime|on|interval=300,max_age=86400,cron=on,cron_min=7\n' > "$NP_TOGGLES_CONF"
PATH="$tmp:$PATH" bash "$INSTALL_CRON" >/dev/null
grep -q 'nervepack-resume-cron' "$tmp_cron" || fail "resume cron entry missing while resume.cron=on"
grep -qE '\*/7 \* \* \* \* .*np-resume-write\.sh --active --throttle' "$tmp_cron" \
  || fail "resume cron schedule/command wrong: $(grep resume-cron "$tmp_cron")"
n="$(grep -c 'nervepack-resume-cron' "$tmp_cron")"
[[ "$n" == "1" ]] || fail "resume cron entry duplicated: $n"

PATH="$tmp:$PATH" bash "$INSTALL_CRON" >/dev/null   # idempotent re-run while still on
n="$(grep -c 'nervepack-resume-cron' "$tmp_cron")"
[[ "$n" == "1" ]] || fail "resume cron entry duplicated on idempotent re-run: $n"

echo "PASS: resume cron entry present, correctly scheduled, and idempotent while on"

export NP_TOGGLES_CONF="$tmp/toggles-cron-off2.conf"
printf 'resume|shared|runtime|on|interval=300,max_age=86400,cron=off,cron_min=5\n' > "$NP_TOGGLES_CONF"
PATH="$tmp:$PATH" bash "$INSTALL_CRON" >/dev/null
grep -q 'nervepack-resume-cron' "$tmp_cron" && fail "stale resume cron entry not removed after flipping to off"

echo "PASS: flipping resume.cron back to off removes the stale entry"
unset NP_TOGGLES_CONF

# === 4. Writer --active: discovers the newest non-agent-* transcript and writes
#        a pointer for it; silently exits 0 when no candidate exists. ===
PROJECTS="$tmp/projects"
mkdir -p "$PROJECTS/proj1"
REPO="$tmp/active-repo"
mkdir -p "$REPO"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email "test@example.com"
git -C "$REPO" config user.name "Test"
echo hi > "$REPO/README.md"
git -C "$REPO" add README.md
git -C "$REPO" commit -q -m baseline

# An OLDER agent-* transcript (must be skipped) and a NEWER real session transcript.
cat > "$PROJECTS/proj1/agent-should-be-skipped.jsonl" <<EOF
{"type":"user","promptSource":"typed","message":{"role":"user","content":"wrong one"},"cwd":"$REPO"}
EOF
sleep 1.1   # ensure a distinct (newer) mtime — mtime granularity is 1s on some filesystems
cat > "$PROJECTS/proj1/real-session-abc.jsonl" <<EOF
{"type":"user","promptSource":"typed","message":{"role":"user","content":"do the active thing"},"cwd":"$REPO"}
EOF

export CLAUDE_PROJECTS_DIR="$PROJECTS"
export NP_RESUME_POINTER="$tmp/pointer-active.json"
export NP_RESUME_STAMP="$tmp/last-write-active"
export NP_RESUME_LOG="$tmp/resume-active.log"
export NP_TOGGLES_CONF="$tmp/toggles-empty.conf"; : > "$NP_TOGGLES_CONF"

bash "$WRITER" --active

[[ -f "$NP_RESUME_POINTER" ]] || fail "--active did not write a pointer"
jq -e '.session_id == "real-session-abc"' "$NP_RESUME_POINTER" >/dev/null \
  || fail "--active picked the wrong session: $(jq -c . "$NP_RESUME_POINTER")"
jq -e --arg v "$REPO" '.cwd == $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "--active cwd mismatch: $(jq -c . "$NP_RESUME_POINTER")"

echo "PASS: writer --active discovers the newest non-agent-* transcript"

# --active composes with --throttle: within the interval, a second --active call
# must NOT overwrite the pointer with a (fake) different newest session.
cat > "$PROJECTS/proj1/agent-should-be-skipped.jsonl" <<EOF
{"type":"user","promptSource":"typed","message":{"role":"user","content":"still wrong"},"cwd":"$REPO"}
EOF
date +%s > "$NP_RESUME_STAMP"
bash "$WRITER" --active --throttle
jq -e '.session_id == "real-session-abc"' "$NP_RESUME_POINTER" >/dev/null \
  || fail "--active --throttle should not have rewritten the pointer within the interval"

echo "PASS: writer --active composes with --throttle"

# --active with no candidate transcripts -> silent exit 0, no pointer written.
empty_projects="$tmp/empty-projects"; mkdir -p "$empty_projects"
export CLAUDE_PROJECTS_DIR="$empty_projects"
rm -f "$NP_RESUME_POINTER"
rc=0; out="$(bash "$WRITER" --active 2>&1)" || rc=$?
[[ "$rc" == 0 ]] || fail "--active with no candidates should exit 0, got $rc"
[[ -f "$NP_RESUME_POINTER" ]] && fail "--active with no candidates should not write a pointer"
[[ -z "$out" ]] || fail "--active with no candidates should be silent, got: $out"

echo "PASS: writer --active with no candidate transcripts exits 0 silently"

echo "PASS test_resume_install"
