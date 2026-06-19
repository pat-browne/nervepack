#!/usr/bin/env bash
# Resolve the dashboard URL for the two open paths (74-open-dashboard.sh hook and
# the manual open-dashboard.sh). SOURCE this; it defines np_dashboard_url.
#
# When evaluator.dashboard_serve is "on" (a param, default on — opt-out), it ensures
# the local backend (np-dashboard-server.py) is running on 127.0.0.1:<port> and
# returns the http URL so the dashboard's action buttons work. Set the param to "off"
# to fall back to the static file:// URL (no server, no action buttons). Fail-open:
# any trouble starting the server still yields a usable URL.
#
# This is the only place that starts the (opt-in, localhost-only) daemon — a
# documented exception to nervepack's "no service, no daemon" invariant.

_npd_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Self-contained: pull in the toggle resolver if the caller hasn't already.
if ! declare -F np_param >/dev/null 2>&1; then
  # shellcheck source=/dev/null
  source "$_npd_here/np-toggle-lib.sh"
fi

_npd_listening() {  # $1=port -> 0 if something is accepting on 127.0.0.1:port
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

np_dashboard_url() {
  local here np port top server
  here="$_npd_here"; np="$(cd "$here/../.." && pwd)"   # engine/setup -> repo root
  if [[ "$(np_param evaluator.dashboard_serve on)" != "on" ]]; then
    printf 'file://%s/dashboard/index.html' "$np"; return 0
  fi
  port="$(np_param evaluator.dashboard_port 8787)"
  top="$(np_param evaluator.suggestions_top 10)"
  server="$here/np-dashboard-server.py"
  if ! _npd_listening "$port"; then
    NP_DASH_PORT="$port" NP_SUGGESTIONS_TOP="$top" \
      nohup python3 "$server" >/dev/null 2>&1 </dev/null &
    disown 2>/dev/null || true
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
      _npd_listening "$port" && break
      sleep 0.2
    done
  fi
  # Fall back to file:// if the server never came up (fail-open).
  if _npd_listening "$port"; then
    printf 'http://127.0.0.1:%s/' "$port"
  else
    printf 'file://%s/dashboard/index.html' "$np"
  fi
}
