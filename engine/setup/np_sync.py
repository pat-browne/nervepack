"""Bash-free Python port of 40-sync-nervepack.sh's defensive engine sync.

Fetches origin/main and fast-forwards the local clone ONLY when the working tree
is clean AND local HEAD is a strict ancestor of origin/main — never autostashes,
rebases, or touches a dirty tree. Uses native git (no bash). The MCP server's
_tool_sync runs this as the bash-free fallback; when bash is available it runs the
full 40-sync-nervepack.sh (which also does the team-layer ff + the Claude-Code
skill relink — both out of scope here). Slice 4 of the git-for-windows-free MCP
work (#38).

Parity-locked (status-message outcome, modulo the embedded UTC timestamp) to the
bash original by tests/mcp/parity/test_sync_parity.sh. stdlib only.
"""
import os
import subprocess
import sys
import time

import np_toggle


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())   # date -u +%FT%TZ


def _git(target, *args):
    return subprocess.run(["git", "-C", target, *args], capture_output=True, text=True)


def _is_ancestor(target, a, b):
    return _git(target, "merge-base", "--is-ancestor", a, b).returncode == 0


def _count(target, rng):
    r = _git(target, "rev-list", "--count", rng)
    return r.stdout.strip() if r.returncode == 0 else "?"


def _porcelain_count(target):
    out = _git(target, "status", "--porcelain").stdout
    return sum(1 for ln in out.splitlines())


def _is_dirty(target):
    tracked_dirty = _git(target, "diff-index", "--quiet", "HEAD", "--").returncode != 0
    untracked = _git(target, "ls-files", "--others", "--exclude-standard").stdout.strip()
    return tracked_dirty or bool(untracked)


def sync(mode="backup"):
    """Run the defensive sync; return the single outcome line (matching what the
    bash script echoes / writes to the status file)."""
    if not np_toggle.enabled("sync"):
        return "nervepack-sync: disabled via toggle — skipping"

    stamp = os.environ.get("NP_SYNC_STAMP") or os.path.join(
        _home(), ".cache", "nervepack", "last-sync")
    if mode != "exit":
        try:
            interval = int(np_toggle.param("sync.interval", "86400") or "86400")
        except ValueError:
            interval = 86400
        if os.path.isfile(stamp):
            try:
                last = int((open(stamp, encoding="utf-8").read().strip() or "0"))
            except (ValueError, OSError):
                last = 0
            age = int(time.time()) - last
            if age < interval:
                return "nervepack-sync: within %ds interval (age %ds) — skipping (backup)" % (interval, age)
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass
    if os.environ.get("NP_SYNC_DRYRUN") == "1":
        return "nervepack-sync: would sync now (mode=%s)" % mode

    target = os.environ.get("NP_SYNC_TARGET") or os.path.join(_home(), "Code", "nervepack")
    status_file = os.environ.get("NP_SYNC_STATUS") or os.path.join(
        _home(), ".cache", "np-core-sync-status")

    def write_status(msg):
        try:
            os.makedirs(os.path.dirname(status_file), exist_ok=True)
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass
        return msg

    if not os.path.isdir(os.path.join(target, ".git")):
        return write_status("np-core-sync: %s — %s is not a git repo" % (_now(), target))

    fetch = _git(target, "fetch", "--quiet", "origin", "main")
    if fetch.returncode != 0:
        return write_status("np-core-sync: %s — fetch failed: %s" % (_now(), fetch.stderr.strip()))

    local = _git(target, "rev-parse", "HEAD").stdout.strip()
    remote = _git(target, "rev-parse", "origin/main").stdout.strip()
    dirty = _is_dirty(target)

    if local == remote:                                    # up to date
        if not dirty:
            sh = _git(target, "rev-parse", "--short", "HEAD").stdout.strip()
            return write_status("np-core-sync: %s — up to date (%s)" % (_now(), sh))
        return write_status("np-core-sync: %s — up to date with origin (%d uncommitted change(s) in working tree)"
                            % (_now(), _porcelain_count(target)))
    if dirty:                                              # dirty + behind -> never touch
        return write_status("np-core-sync: %s — SKIPPED (working tree dirty: %d files; %s remote commits waiting). "
                            "Commit/stash, then re-run /np-core-sync." % (_now(), _porcelain_count(target), _count(target, "HEAD..origin/main")))
    if _is_ancestor(target, remote, local):                # local ahead
        return write_status("np-core-sync: %s — local is %s commit(s) ahead of origin/main. Push when ready."
                            % (_now(), _count(target, "origin/main..HEAD")))
    if _is_ancestor(target, local, remote):                # safe fast-forward
        pulled = _count(target, "HEAD..origin/main")
        ff = _git(target, "merge", "--ff-only", "--quiet", "origin/main")
        if ff.returncode == 0:
            sh = _git(target, "rev-parse", "--short", "HEAD").stdout.strip()
            return write_status("np-core-sync: %s — fast-forwarded %s commit(s) to %s" % (_now(), pulled, sh))
        return write_status("np-core-sync: %s — ff-only merge failed: %s" % (_now(), ff.stderr.strip()))
    # diverged -> never auto-resolve
    return write_status("np-core-sync: %s — DIVERGED (%s local-only, %s remote-only commits). "
                        "Resolve: cd ~/Code/nervepack && git pull --rebase --autostash"
                        % (_now(), _count(target, "origin/main..HEAD"), _count(target, "HEAD..origin/main")))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    mode = "exit" if "exit" in sys.argv[1:] else "backup"
    sys.stdout.write(sync(mode) + "\n")
