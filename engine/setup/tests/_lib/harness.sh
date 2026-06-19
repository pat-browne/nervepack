#!/usr/bin/env bash
# Hermetic environment for the regression runner. Sourced by run-all.sh BEFORE any
# child test runs. Goal: reproduce the standalone dev environment but isolated from
# the real ~/.config and ~/.cache, with the model seam stubbed so nothing hits a
# network or a real `claude`. Individual tests still mktemp their own working dirs;
# this just guarantees a clean, side-effect-free HOME for the whole run.
np_hermetic_env() {
  NP_TEST_HOME="$(mktemp -d)"
  export HOME="$NP_TEST_HOME"
  export XDG_CACHE_HOME="$NP_TEST_HOME/.cache"
  export XDG_CONFIG_HOME="$NP_TEST_HOME/.config"
  mkdir -p "$XDG_CACHE_HOME/nervepack" "$XDG_CONFIG_HOME/nervepack"
  local stub="$NP_TEST_HOME/claude-stub"
  cat > "$stub" <<'STUB'
#!/usr/bin/env bash
echo "STUB CLAUDE invoked in a test without an explicit CLAUDE_BIN override" >&2
exit 97
STUB
  chmod +x "$stub"
  export CLAUDE_BIN="$stub"
  export NP_LLM_BACKEND="${NP_LLM_BACKEND:-claude}"
}

np_hermetic_cleanup() { [[ -n "${NP_TEST_HOME:-}" ]] && rm -rf "$NP_TEST_HOME"; }
