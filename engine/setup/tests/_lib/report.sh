#!/usr/bin/env bash
# Functionality-grouped Markdown report emitter for the regression runner.
# The runner records one line per test into a TSV ($1) as: <area>\t<role>\t<name>\t<PASS|FAIL>
# np_emit_report <results.tsv> <output.md> <pass_count> <fail_count> <seconds>
np_emit_report() {
  local tsv="$1" out="$2" passed="$3" failed="$4" secs="$5"
  local funcs; funcs="$(cut -f1 "$tsv" | sort -u | grep -c . || true)"
  {
    echo "# nervepack regression report"
    echo
    if [[ "$failed" -eq 0 ]]; then echo "**✅ $passed passed / $failed failed** · $funcs functionalities · ${secs}s"
    else echo "**❌ $passed passed / $failed failed** · $funcs functionalities · ${secs}s"; fi
    echo
    local area
    while IFS= read -r area; do
      [[ -n "$area" ]] || continue
      echo "## $area"
      echo
      echo "| test | role | status |"
      echo "|---|---|---|"
      awk -F'\t' -v a="$area" '$1==a {
        s=($4=="PASS")?"✅":"❌";
        printf "| %s | %s | %s |\n", $3, $2, s
      }' "$tsv"
      echo
    done < <(cut -f1 "$tsv" | sort -u)
  } > "$out"
}
