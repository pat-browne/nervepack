"""E2e test harness: boots np-dashboard-server.py in an isolated env, returns (base_url, stop_fn).

Path layout (harness.py is at engine/setup/tests/e2e/harness.py):
  e2e_dir = Path(__file__).resolve().parent  -> .../engine/setup/tests/e2e/
  e2e_dir.parents[0]                         -> .../engine/setup/tests/
  e2e_dir.parents[1]                         -> .../engine/setup/
  e2e_dir.parents[2]                         -> .../engine/
  e2e_dir.parents[3]                         -> repo root (regression-suite/)
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_metrics_js(metrics_jsonl: str, out_js: str) -> None:
    """Convert a metrics.jsonl fixture into the window.METRICS = [...] JS the dashboard loads."""
    records = []
    with open(metrics_jsonl) as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    js = "window.METRICS = " + json.dumps(records) + ";\nwindow.LEARNED = {playbooks:0,strategies:0,strategy_names:[]};\n"
    with open(out_js, "w") as fh:
        fh.write(js)


def start(stub_state: str = "done", metrics_path: str | None = None) -> tuple[str, callable]:
    """Boot the dashboard server in a temp-isolated env. Returns (base_url, stop_fn)."""
    e2e_dir = Path(__file__).resolve().parent
    # parents[3] of e2e_dir (which is .../engine/setup/tests/e2e/) == repo root
    repo_root = e2e_dir.parents[3]
    server_script = repo_root / "engine" / "setup" / "np-dashboard-server.py"
    real_dashboard = repo_root / "dashboard"

    if not server_script.exists():
        raise FileNotFoundError(f"np-dashboard-server.py not found at {server_script}")

    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="np_e2e_")

    if metrics_path is None:
        metrics_path = str(e2e_dir / "fixtures" / "metrics.jsonl")

    # Build an isolated dashboard root so we don't touch the real dashboard/data/.
    # The server serves data/metrics.js as a static file — we must create it.
    dash_root = os.path.join(tmp, "dashboard")
    os.makedirs(dash_root)
    shutil.copy(str(real_dashboard / "index.html"), os.path.join(dash_root, "index.html"))
    data_dir = os.path.join(dash_root, "data")
    os.makedirs(data_dir)
    _build_metrics_js(metrics_path, os.path.join(data_dir, "metrics.js"))
    # Stub out metrics.js.map / any other files the server might 404 on — not needed.

    env = {
        **os.environ,
        "NP_DASH_PORT": str(port),
        "NP_DASH_ROOT": dash_root,
        "NP_METRICS": metrics_path,
        "NP_RESOLVED_SUGGESTIONS": os.path.join(tmp, "resolved.json"),
        "NP_IMPLEMENT": str(e2e_dir / "stub-implement.sh"),
        "NP_IMPLEMENT_STATUS_DIR": os.path.join(tmp, "status"),
        "NP_TOGGLES_LOCAL": os.path.join(tmp, "toggles.json"),
        "NP_RESOLVE_NO_BUILD": "1",
        "NP_STUB_STATE": stub_state,
        "HOME": tmp,
    }

    proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = f"http://127.0.0.1:{port}"

    # Wait up to 10s for /api/health
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base_url}/api/health", timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise RuntimeError(
                    f"Server exited early (code {proc.returncode}):\n{err.decode()}\n{out.decode()}"
                )
            time.sleep(0.2)
    else:
        proc.terminate()
        raise TimeoutError(f"Dashboard server did not start on port {port} within 10s")

    def stop():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    return base_url, stop
