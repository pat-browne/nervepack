#!/usr/bin/env bash
# np-test: dashboard-launch | happy+failure
# np_dashboard_url() (np-dashboard-launch.sh) resolves the dashboard URL for the
# two open paths. Three branches, all asserted by the RESOLVED URL string (no real
# browser, no real long-lived server):
#   A. evaluator.dashboard_serve=off            -> file://.../dashboard/index.html
#   B. serve=on AND a backend already listening -> http://127.0.0.1:<port>/
#   C. serve=on but the backend never comes up  -> file:// fallback (fail-open)
# For (B) we stand up a throwaway TCP listener on a free port (so the helper's
# pre-flight check sees a live socket and does NOT spawn the real server). For (C)
# we point at a definitely-dead port AND neuter the spawn (no-op python3/nohup on
# PATH) so nothing real launches and the wait loop falls through to file://.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH="$HERE/../../np-dashboard-launch.sh"
NP="$(cd "$HERE/../../../.." && pwd)"   # engine/setup/tests/evaluator -> repo root
INDEX_FILE="$NP/dashboard/index.html"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"; [[ -n "${LPID:-}" ]] && kill "$LPID" 2>/dev/null || true' EXIT

free_port() { python3 - <<'PY'
import socket
s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()
PY
}

# --- A. serve=off -> file:// -------------------------------------------------
cat > "$tmp/toggles.conf" <<'C'
evaluator|shared|runtime|on|dashboard_serve=off,dashboard_port=8787
C
url="$(NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
  bash -c "source '$LAUNCH'; np_dashboard_url")"
[[ "$url" == "file://$NP/dashboard/index.html" ]] \
  || { echo "FAIL(A): serve=off url=$url (want file://$NP/dashboard/index.html)"; exit 1; }
[[ -f "$INDEX_FILE" ]] || { echo "FAIL(A): file:// target does not exist: $INDEX_FILE"; exit 1; }

# --- B. serve=on + live listener -> http:// ----------------------------------
PORT="$(free_port)"
# Park a real socket on PORT so _npd_listening sees a connectable backend and the
# helper returns the http URL WITHOUT spawning np-dashboard-server.py.
python3 - "$PORT" <<'PY' &
import socket, sys, time
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(8)
time.sleep(30)
PY
LPID=$!
# wait for the listener to be up
for _ in $(seq 1 50); do (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break; sleep 0.1; done
cat > "$tmp/toggles.conf" <<C
evaluator|shared|runtime|on|dashboard_serve=on,dashboard_port=$PORT
C
url="$(NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
  bash -c "source '$LAUNCH'; np_dashboard_url")"
[[ "$url" == "http://127.0.0.1:$PORT/" ]] \
  || { echo "FAIL(B): serve=on+listener url=$url (want http://127.0.0.1:$PORT/)"; exit 1; }
kill "$LPID" 2>/dev/null || true; LPID=""

# --- C. serve=on + backend never comes up -> file:// fallback ----------------
DEAD="$(free_port)"   # free now; we neuter the spawn so it stays dead
# No-op python3 + nohup on PATH so the helper's `nohup python3 server &` launches
# nothing real (and we never bind DEAD). The listening probe stays false -> file://.
mkdir -p "$tmp/bin"
printf '#!/usr/bin/env bash\nexit 0\n' > "$tmp/bin/nohup";  chmod +x "$tmp/bin/nohup"
# Keep a usable python3 for the toggle lib? np-toggle-lib is pure bash; the helper
# only uses python3 via the (now no-op nohup-wrapped) server spawn, so stubbing
# nohup alone is enough — leave python3 intact.
cat > "$tmp/toggles.conf" <<C
evaluator|shared|runtime|on|dashboard_serve=on,dashboard_port=$DEAD
C
url="$(PATH="$tmp/bin:$PATH" NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
  bash -c "source '$LAUNCH'; np_dashboard_url")"
[[ "$url" == "file://$NP/dashboard/index.html" ]] \
  || { echo "FAIL(C): dead-server fallback url=$url (want file://$NP/dashboard/index.html)"; exit 1; }

echo "PASS test_dashboard_launch"
