#!/usr/bin/env bash
# np-instruction-block.sh — manage nervepack's additive @import block in a host
# instruction file (CLAUDE.md / AGENTS.md / .cursor rule). Additive, idempotent,
# removable: only the fenced block is ever touched. Sourceable or run as CLI.
set -uo pipefail

NP_BLOCK_BEGIN='<!-- nervepack:begin (managed — do not edit; remove via np-instruction-block.sh remove) -->'
NP_BLOCK_END='<!-- nervepack:end -->'
: "${NP_DIRECTIVE_PATH:=$HOME/Code/nervepack/engine/setup/nervepack-session-directive.md}"

np_instruction_block_remove() {  # $1 = target file
  local file="$1" tmp
  [[ -n "$file" ]] || { echo "np-instruction-block: no file given" >&2; return 2; }
  [[ -f "$file" ]] || return 0
  tmp="$(mktemp)"
  awk -v b="$NP_BLOCK_BEGIN" -v e="$NP_BLOCK_END" '
    $0==b { inblk=1; begin_line=b; delete buf; bufn=0; next }
    inblk && $0==e { inblk=0; bufn=0; next }
    inblk { buf[bufn++]=$0; next }
    { print }
    END { if (inblk) { print begin_line; for (i=0;i<bufn;i++) print buf[i] } }
  ' "$file" > "$tmp" && mv "$tmp" "$file"
}

np_instruction_block_install() {  # $1 = target file
  local file="$1" tmp
  [[ -n "$file" ]] || { echo "np-instruction-block: no file given" >&2; return 2; }
  mkdir -p "$(dirname "$file")"
  [[ -f "$file" ]] || : > "$file"
  np_instruction_block_remove "$file"        # strip any prior block (idempotent)
  tmp="$(mktemp)"
  {
    cat "$file"
    [[ -s "$file" ]] && printf '\n'
    printf '%s\n' "$NP_BLOCK_BEGIN"
    printf '@%s\n' "$NP_DIRECTIVE_PATH"
    printf '%s\n' "$NP_BLOCK_END"
  } > "$tmp" && mv "$tmp" "$file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    install) np_instruction_block_install "${2:-}" ;;
    remove)  np_instruction_block_remove  "${2:-}" ;;
    *) echo "usage: np-instruction-block.sh {install|remove} <file>" >&2; exit 2 ;;
  esac
fi
