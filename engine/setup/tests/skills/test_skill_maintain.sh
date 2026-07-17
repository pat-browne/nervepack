#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"     # setup/
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Minimal nervepack-shaped repo (engine/ split: engine code under engine/setup,
# content — skills/, agents/ — at the repo root, matching the real layout).
NP="$tmp/np"; mkdir -p "$NP/engine/setup" "$NP/skills/big/" "$NP/agents"
cp "$SETUP/75-skill-maintain.sh" "$SETUP/np_skill_budget.py" \
   "$SETUP/np-skill-validate.py" "$SETUP/np-toggle-lib.sh" "$SETUP/np-llm.sh" \
   "$SETUP/np-content-lib.sh" "$SETUP/np_graduation_detect.py" "$NP/engine/setup/"
printf 'skills|shared|runtime|on|split_kb=8,soft_kb=6,catalog_tok=4000,max_per_run=2,graduate_seen=10,graduate_kb=6\n' \
   > "$NP/engine/setup/toggles.conf"
{ echo "## Prompt"; echo "split it"; } > "$NP/agents/np-flow-skill-maintain.md"
# A proven lesson under memory/lessons/ (content dir defaults to the repo root).
mkdir -p "$NP/memory/lessons"
printf -- '---\nname: proven\nkind: lesson\nprovenance: failure\nstatus: candidate\nseen: 20\n---\nbody\n' \
   > "$NP/memory/lessons/proven.md"
# An over-budget skill (>8KB) with a cross-link.
{ printf -- '---\nname: big\ndescription: a big skill\n---\n[[np-core-sync]]\n';
  head -c 9000 /dev/zero | tr '\0' 'x'; } > "$NP/skills/big/SKILL.md"
( cd "$NP" && git init -q && git config user.email "t@t" && git config user.name "t" && git add -A && git commit -qm init )

run_with_stub() {  # $1 = stub body
  cat > "$tmp/claude" <<STUB
#!/usr/bin/env bash
cat >/dev/null   # consume the piped prompt
$1
STUB
  chmod +x "$tmp/claude"
  ( cd "$NP" && CLAUDE_BIN="$tmp/claude" SKILL_MAINTAIN_NO_PUSH=1 \
      SKILL_MAINTAIN_LOG="$tmp/log" GRADUATION_MARKER="$tmp/grad" NP_CONTENT_DIR="$NP" \
      bash engine/setup/75-skill-maintain.sh >/dev/null 2>&1 )
}

# --- GOOD split: shrink body, add references/, keep frontmatter + link ---
run_with_stub '
mkdir -p skills/big/references
printf -- "---\nname: big\ndescription: a big skill\n---\nRule. Detail: references/d.md\n[[np-core-sync]]\n" > skills/big/SKILL.md
printf "long detail\n" > skills/big/references/d.md'
test -f "$NP/skills/big/references/d.md" || { echo "FAIL: good split not applied"; exit 1; }
# Capture-then-grep: piping `git log` into `grep -q` is racy under `set -o pipefail` —
# grep -q exits on the first match, git log then dies of SIGPIPE (141), and pipefail
# propagates that as failure even though the match succeeded (reliably bites on macOS).
grep -q 'skill(maintain)' <<<"$(git -C "$NP" log --oneline)" || { echo "FAIL: good split not committed"; exit 1; }

# --- graduation surfacing: the proven lesson is flagged (advisory, not acted on) ---
grep -q 'GRADUATE: failure proven' "$tmp/log" || { echo "FAIL: graduation candidate not surfaced in log"; exit 1; }
test -f "$tmp/grad" || { echo "FAIL: graduation marker file not written"; exit 1; }
grep -q '"name":"proven"' "$tmp/grad" || { echo "FAIL: marker missing the candidate"; exit 1; }
# Committed, content-routed data file the dashboard build reads (mirror of the local
# marker; lives under the CONTENT overlay's dashboard/data/, here == $NP).
GRAD_DATA="$NP/dashboard/data/graduation-candidates.json"
test -f "$GRAD_DATA" || { echo "FAIL: committed graduation data file not written"; exit 1; }
grep -q '"name":"proven"' "$GRAD_DATA" || { echo "FAIL: data file missing the candidate"; exit 1; }

# Reset to the over-budget state for the abort case
( cd "$NP" && git revert --no-edit HEAD >/dev/null 2>&1 )

# --- BAD split: changes description -> validator fails -> revert, no commit ---
before="$(cd "$NP" && git rev-parse HEAD)"
run_with_stub '
mkdir -p skills/big/references
printf -- "---\nname: big\ndescription: CHANGED\n---\nRule references/d.md [[np-core-sync]]\n" > skills/big/SKILL.md
printf "d\n" > skills/big/references/d.md'
after="$(cd "$NP" && git rev-parse HEAD)"
[[ "$before" == "$after" ]] || { echo "FAIL: bad split was committed"; exit 1; }
test ! -e "$NP/skills/big/references" || { echo "FAIL: bad split refs not cleaned"; exit 1; }
grep -q 'CHANGED' "$NP/skills/big/SKILL.md" && { echo "FAIL: bad edit not reverted"; exit 1; }
echo "PASS test_skill_maintain"
