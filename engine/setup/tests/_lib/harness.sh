#!/usr/bin/env bash
# Hermetic environment for the regression runner. Sourced by run-all.sh BEFORE any
# child test runs. Goal: reproduce the standalone dev environment but isolated from
# the real ~/.config and ~/.cache, with the model seam stubbed so nothing hits a
# network or a real `claude`. Individual tests still mktemp their own working dirs;
# this just guarantees a clean, side-effect-free HOME for the whole run.
np_hermetic_env() {
  NP_TEST_HOME="$(mktemp -d)"
  export HOME="$NP_TEST_HOME"
  # UNSET rather than exported. np_dirs derives ~/.cache and ~/.config from HOME
  # when these are unset, so exporting them here only duplicated the default --
  # and it broke isolation for every test that redirects HOME on its own, which
  # kept reading the harness's directories instead of its own. Unsetting also
  # stops a developer's real XDG_* leaking in, which the export used to mask.
  #
  # CONSEQUENCE FOR TEST AUTHORS: the harness no longer guarantees these are set.
  # A test that wants to exercise XDG behaviour must set them itself, alongside
  # HOME -- see tests/mcp/test_mcp_lifecycle.py, which already does exactly that.
  unset XDG_CACHE_HOME XDG_CONFIG_HOME
  mkdir -p "$NP_TEST_HOME/.cache/nervepack" "$NP_TEST_HOME/.config/nervepack"
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
  # deterministically on EVERY host. np_hook.py otherwise auto-wraps as
  # `bash -lc '<cmd>'` on a Git-bash (MINGW/MSYS) kernel — correct at runtime, but it
  # would break the exact-form assertions in the install-hook tests when the suite runs
  # on the Windows CI lane. The Windows wrap itself stays covered by the explicit
  # NP_HOOK_WRAP=1 cases in tests/nervepack_engine/test_np_hook.py.
  export NP_HOOK_WRAP="${NP_HOOK_WRAP:-0}"
}

np_hermetic_cleanup() { [[ -n "${NP_TEST_HOME:-}" ]] && rm -rf "$NP_TEST_HOME"; }
