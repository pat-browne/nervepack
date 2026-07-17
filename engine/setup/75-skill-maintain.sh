#!/usr/bin/env bash
# Daily skill-maintenance: detect over-budget skills, split overflow into
# references/ via a gated Sonnet pass, validate-or-abort, commit + push.
# Deterministic-first (no LLM unless there's work). Fail-open. Gated by the
# `skills` toggle (+ `skills.split`). Thresholds via toggle params.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
source "$HERE/np-toggle-lib.sh"
source "$HERE/np-content-lib.sh" 2>/dev/null || true   # np_content_dir (graduation scan)
source "$HERE/np-layer-lib.sh" 2>/dev/null || true     # np_merge_roots (skill roots: engine + overlay [+ team])
np_enabled skills || { echo "$(date -u +%FT%TZ) skipped: skills disabled"; exit 0; }

LOG="${SKILL_MAINTAIN_LOG:-$HOME/.cache/nervepack/skill-maintain.log}"
GRAD_MARKER="${GRADUATION_MARKER:-$HOME/.cache/nervepack/graduation-candidates}"
mkdir -p "$(dirname "$LOG")"
CLAUDE="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
PROMPT_FILE="$NP/agents/np-flow-skill-maintain.md"

command -v jq  >/dev/null || { echo "$(date -u +%FT%TZ) jq missing" >>"$LOG"; exit 0; }
command -v python3 >/dev/null || { echo "$(date -u +%FT%TZ) python3 missing" >>"$LOG"; exit 0; }

# docs/ARCHITECTURE.md freshness (advisory, deterministic): flag features/specs that
# exist but aren't referenced in the map. Drift is logged + left in a marker file
# so it's discoverable; never blocks the skill-maintenance work below.
fresh_out="$("$HERE/np-architecture-freshness.sh" 2>/dev/null || true)"
printf '%s %s\n' "$(date -u +%FT%TZ)" "$(printf '%s' "$fresh_out" | tail -1)" >>"$LOG"
if printf '%s' "$fresh_out" | grep -q '^STALE:'; then
  printf '%s' "$fresh_out" | grep '^STALE:' >>"$LOG"
  printf '%s\n' "$fresh_out" > "$HOME/.cache/nervepack/architecture-stale"
else
  rm -f "$HOME/.cache/nervepack/architecture-stale" 2>/dev/null || true
fi

# Graduation candidates (advisory, deterministic): lessons that have
# proven themselves (`seen` >= graduate_seen) or outgrown the skill body budget
# (bytes > graduate_kb KB) are overdue to GRADUATE into a human-reviewed skill via
# np-core-contribute. Skills require the human gate, so we only SURFACE candidates
# (marker file + log) — never auto-promote. Mirrors the architecture-freshness check.
# Issue #12: the graduation block writes graduation-candidates.json INTO the content
# overlay's dashboard/data/. If the content dir resolved via the IMPLICIT engine-root
# fallback (NP_CONTENT_DIR unset AND no ~/.config/nervepack/content-dir), that would write
# personal-content data into the PII-clean engine repo — so skip the graduation scan on the
# implicit fallback (the engine skill-split work below still runs; it commits engine skills
# to $NP, which is correct regardless of content dir). A deliberate single-repo user opts in
# via the config file (origin 'config') and the scan runs as before.
if command -v np_content_dir >/dev/null 2>&1 && np_content_is_explicit 2>/dev/null \
     && CONTENT="$(np_content_dir 2>/dev/null)"; then
  export GRADUATE_SEEN="$(np_param skills.graduate_seen 10)"
  export GRADUATE_KB="$(np_param skills.graduate_kb 6)"
  grad_out="$(python3 "$HERE/np_graduation_detect.py" "$CONTENT/memory/lessons" 2>/dev/null)"
  grad_n="$(printf '%s' "$grad_out" | jq -r '.candidates | length' 2>/dev/null || echo 0)"
  # Committed, content-routed data file the dashboard build reads (the local marker is
  # cache-only, so build.py — which may run from committed data in cloud/CI — can't see
  # it). Mirrors the resolved-suggestions ledger: written under the CONTENT overlay's
  # dashboard/data/ (candidates derive from personal lessons — keeps the
  # engine PII-clean), read by build.py load_graduation() -> window.GRADUATION panel.
  GRAD_DATA="$CONTENT/dashboard/data/graduation-candidates.json"
  if [[ "${grad_n:-0}" -gt 0 ]]; then
    printf '%s' "$grad_out" | jq -r '.candidates[] | "GRADUATE: \(.kind) \(.name) (seen=\(.seen), bytes=\(.bytes)) [\(.reasons|join("+"))] -> promote to a skill"' >>"$LOG"
    printf '%s\n' "$grad_out" > "$GRAD_MARKER"
    mkdir -p "$(dirname "$GRAD_DATA")" && printf '%s\n' "$grad_out" > "$GRAD_DATA"
    echo "$(date -u +%FT%TZ) graduation: $grad_n candidate(s) — see $GRAD_MARKER" >>"$LOG"
  else
    rm -f "$GRAD_MARKER" 2>/dev/null || true
    # No candidates -> write an empty data file so a previously-surfaced panel clears
    # (rather than going stale on the last non-empty snapshot). Only when the overlay's
    # dashboard/data/ already exists, to avoid creating it on hosts that don't dashboard.
    [[ -d "$(dirname "$GRAD_DATA")" ]] && printf '%s\n' "$grad_out" > "$GRAD_DATA"
  fi
fi

# Resolve tunable params -> env for the python helpers.
export SKILL_SPLIT_KB="$(np_param skills.split_kb 8)"
export SKILL_SOFT_KB="$(np_param skills.soft_kb 6)"
export SKILL_CATALOG_TOK="$(np_param skills.catalog_tok 4000)"
MAX_PER_RUN="$(np_param skills.max_per_run 2)"

# Skill roots to scan: the engine's skills/ ALWAYS, plus the content-overlay's
# skills/ (and a team overlay's, when merged) when it resolves to something other
# than the engine root itself. Fail-open: an unset/absent/identical overlay just
# leaves the engine root as the sole scan target (single-repo legacy layout).
ROOTS=("$NP/skills")
if declare -f np_merge_roots >/dev/null 2>&1; then
  while IFS= read -r _r; do
    [[ -n "$_r" && "$_r" != "$NP" && -d "$_r/skills" ]] && ROOTS+=("$_r/skills")
  done < <(np_merge_roots 2>/dev/null)
fi

report="$(python3 "$HERE/np_skill_budget.py" "${ROOTS[@]}" 2>/dev/null)"
[[ -n "$report" ]] || { echo "$(date -u +%FT%TZ) detector produced no output" >>"$LOG"; exit 0; }

if [[ "$(printf '%s' "$report" | jq -r '.catalog_over')" == "true" ]]; then
  echo "$(date -u +%FT%TZ) NOTE: catalog over budget ($(printf '%s' "$report" | jq -r '.catalog_tokens') tok) — tree restructure due (manual/future)" >>"$LOG"
fi

cands=()   # bash 3.2 (stock macOS) has no `mapfile` — read into the array with a loop
# Strip a trailing CR: on Windows (Task Scheduler / Git-bash) python3's CRLF stdout and
# jq can leave \r on each value, which would corrupt the "$NP/skills/$skill" path below
# (silent `continue`). No-op on Linux/macOS.
while IFS= read -r _c; do _c="${_c%$'\r'}"; [[ -n "$_c" ]] && cands+=("$_c"); done < <(printf '%s' "$report" | jq -r '.split_candidates[].skill' 2>/dev/null)
if [[ ${#cands[@]} -eq 0 ]]; then
  echo "$(date -u +%FT%TZ) no skills over split threshold (${SKILL_SPLIT_KB}KB)" >>"$LOG"; exit 0
fi

np_enabled skills.split || { echo "$(date -u +%FT%TZ) skills.split disabled; detected: ${cands[*]}" >>"$LOG"; exit 0; }
[[ -f "$PROMPT_FILE" ]] || { echo "$(date -u +%FT%TZ) ERROR: prompt missing" >>"$LOG"; exit 0; }
# Backend-aware: claude backend needs the binary; a local agentic backend needs
# NP_LLM_AGENT_CMD (np-llm.sh agent mode). Don't hard-require claude on a non-Claude host.
BACKEND="${NP_LLM_BACKEND:-claude}"
{ [[ "$BACKEND" == claude && -x "$CLAUDE" ]] || [[ "$BACKEND" != claude && -n "${NP_LLM_AGENT_CMD:-}" ]]; } \
  || { echo "$(date -u +%FT%TZ) ERROR: agent backend unavailable (backend=$BACKEND)" >>"$LOG"; exit 0; }

# Commits use the machine's GLOBAL git identity (the machine owner) — never set a bot identity
# here: CLAUDE.md requires cron commits authored as that identity, and `git config` would
# persist into .git/config and mis-author later interactive commits in this repo.
base_prompt="$(awk '/^## Prompt$/{p=1; next} p' "$PROMPT_FILE")"
committed=0
commit_repos=()   # repos that received a commit this run — each gets pushed once

# Locates which ROOTS entry holds $1 (a skill dir name); prints that root, or
# nothing + non-zero if not found under any scanned root.
find_skill_root() {
  local skill="$1" r
  for r in "${ROOTS[@]}"; do
    [[ -f "$r/$skill/SKILL.md" ]] && { printf '%s\n' "$r"; return 0; }
  done
  return 1
}

for skill in "${cands[@]:0:$MAX_PER_RUN}"; do
  skill_root="$(find_skill_root "$skill")" || continue
  # skill_root is <repo>/skills, so its parent is the repo that owns this skill —
  # the engine ($NP) or a content-overlay repo. Split-and-commit must operate on
  # THAT repo, path-limited, not always $NP (issue #11 pattern, extended to overlays).
  repo_root="$(dirname "$skill_root")"
  dir="$skill_root/$skill"; md="$dir/SKILL.md"
  [[ -f "$md" ]] || continue
  orig="$(mktemp)"
  git -C "$repo_root" show "HEAD:skills/$skill/SKILL.md" > "$orig" 2>/dev/null || cp "$md" "$orig"

  prompt="$base_prompt

TARGET SKILL DIRECTORY: skills/$skill
TARGET SKILL FILE: skills/$skill/SKILL.md
Hard body budget: ${SKILL_SPLIT_KB}KB. Move overflow into skills/$skill/references/."

  # np-llm.sh sets NERVEPACK_AGENT=1 on the backend call so this headless agent's
  # SessionEnd can't re-fire episodic-capture/np-evaluator into a self-recursion loop.
  ( cd "$repo_root" && printf '%s' "$prompt" | "$HERE/np-llm.sh" agent --tools "Read Write Edit" >/dev/null 2>&1 )

  if python3 "$HERE/np-skill-validate.py" "$dir" "$orig" 2>>"$LOG"; then
    git -C "$repo_root" add "skills/$skill" >/dev/null 2>&1
    # Path-limit the commit to this skill dir — a bare commit would sweep any other
    # session's staged work in the shared tree (issue #11 pattern).
    if git -C "$repo_root" commit -q -m "skill(maintain): split $skill into body+references (auto)" -- "skills/$skill" >/dev/null 2>&1; then
      committed=$((committed+1)); echo "$(date -u +%FT%TZ) split OK: $skill ($repo_root)" >>"$LOG"
      already=0
      for r in "${commit_repos[@]:-}"; do [[ "$r" == "$repo_root" ]] && already=1; done
      [[ $already -eq 0 ]] && commit_repos+=("$repo_root")
    fi
  else
    git -C "$repo_root" checkout -- "skills/$skill" >/dev/null 2>&1
    git -C "$repo_root" clean -fdq "skills/$skill" >/dev/null 2>&1
    echo "$(date -u +%FT%TZ) split ABORTED (reverted): $skill" >>"$LOG"
  fi
  rm -f "$orig"
done

[[ "${SKILL_MAINTAIN_NO_PUSH:-0}" == "1" ]] && exit 0
for repo in "${commit_repos[@]:-}"; do
  [[ -n "$repo" ]] && git -C "$repo" push -q origin HEAD:main >/dev/null 2>&1
done
exit 0
