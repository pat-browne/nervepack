"""Pure-Python port of 35-link-dashboard-data.sh -- ensure the engine's
dashboard/data entry is a symlink into the content overlay so index.html can
load data/metrics.js as a relative sibling regardless of where the content
dir lives. Idempotent: no-op if the correct symlink already exists.
Fail-open: any trouble logs one line and returns 0 (a fresh bootstrap is
never blocked).

In a single-repo layout (content dir == engine root) the real dashboard/data
dir already exists -- no symlink needed (a self-referential symlink would
break things), so this is a no-op.

Windows: uses os.symlink directly (a REAL native symlink, requiring either
Developer Mode or admin privilege) -- unlike the bash original, there is no
silent-deep-copy footgun here (os.symlink either succeeds with a real
symlink or raises OSError; it never falls back to copying). When symlink
privilege is unavailable, falls back to a directory junction via
`cmd /c mklink /J` (no admin needed).
"""
import os
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_NP = os.path.dirname(os.path.dirname(_HERE))


def link(np_root=None, content_dir_fn=None):
    np_root = np_root or _NP
    if content_dir_fn is None:
        import np_content
        content_dir_fn = np_content.content_dir

    try:
        content = content_dir_fn()
    except Exception:
        content = ""
    if not content:
        print("35-link-dashboard-data: content dir resolution failed — skipping")
        return 0

    if os.path.abspath(content) == os.path.abspath(np_root):
        print("35-link-dashboard-data: single-repo layout — no symlink needed")
        return 0

    link_path = os.path.join(np_root, "dashboard", "data")
    target = os.path.join(content, "dashboard", "data")

    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        print("35-link-dashboard-data: could not create %s — %s" % (target, exc))
        return 0

    if os.path.islink(link_path):
        current = os.readlink(link_path)
        if os.path.abspath(current) == os.path.abspath(target):
            print("35-link-dashboard-data: ok (already correct symlink -> %s)" % target)
            return 0
        try:
            os.remove(link_path)
        except OSError as exc:
            print("35-link-dashboard-data: could not remove stale symlink %s -> %s — %s"
                  % (link_path, current, exc))
            return 0
        print("35-link-dashboard-data: replaced stale symlink (%s -> %s)" % (current, target))
    elif os.path.exists(link_path):
        print("35-link-dashboard-data: %s exists and is not a symlink — skipping "
              "(remove it manually to enable the bridge)" % link_path)
        return 0

    try:
        os.symlink(target, link_path, target_is_directory=True)
        print("35-link-dashboard-data: linked %s -> %s" % (link_path, target))
        return 0
    except OSError:
        pass

    if os.name == "nt":
        try:
            if os.path.exists(link_path):
                os.rmdir(link_path)
        except OSError:
            pass
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link_path, target],
                            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            print("35-link-dashboard-data: linked via junction %s -> %s" % (link_path, target))
            return 0
        print("35-link-dashboard-data: could not create native symlink or junction for %s -> %s"
              % (link_path, target))
        return 0

    print("35-link-dashboard-data: ln -s failed for %s -> %s" % (link_path, target))
    return 0
