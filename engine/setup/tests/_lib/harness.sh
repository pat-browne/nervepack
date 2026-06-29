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
  # Pin the hook-command form so the suite asserts canonical (unwrapped) registration
  # deterministically on EVERY host. np-hook-lib.sh otherwise auto-wraps as
  # `bash -lc '<cmd>'` on a Git-bash (MINGW/MSYS) kernel — correct at runtime, but it
  # would break the exact-form assertions in the install-hook tests when the suite runs
  # on the Windows CI lane. The Windows wrap itself stays covered by the explicit
  # NP_HOOK_WRAP=1 cases in tests/toggles/test_hook_lib_win_wrap.sh.
  export NP_HOOK_WRAP="${NP_HOOK_WRAP:-0}"
}

np_hermetic_cleanup() { [[ -n "${NP_TEST_HOME:-}" ]] && rm -rf "$NP_TEST_HOME"; }
