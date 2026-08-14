"""Bash-free Python port of 40-sync-nervepack.sh's defensive engine sync (phase 17
of the bash->Python CLI migration — full parity; the last MCP hybrid removed).

Fetches origin/main and fast-forwards the local clone ONLY when the working tree
is clean AND local HEAD is a strict ancestor of origin/main — never autostashes,
rebases, or touches a dirty tree. Uses native git (no bash), routed via
np_bashlib.argv() so it works under Git-bash on Windows.

Full parity with the retired 40-sync-nervepack.sh:
  * toggle gate (sync), backup-vs-exit mode + sync.interval throttle + NP_SYNC_STAMP,
    NP_SYNC_DRYRUN, and the status-file writes (NP_SYNC_STATUS / ~/.cache/np-core-sync-status);
  * the 5 engine cases (up-to-date clean/dirty, dirty+behind, ahead, fast-forward,
    diverged), plus not-a-git and fetch-failed;
  * on a successful fast-forward: relink skills (np_link_skills.link, in-process),
    re-apply hook registration (np_hook.install_hooks, in-process), and re-run the
    remaining non-hook [56][0-9]-install-*.sh installers from the SYNCED target;
  * the optional team-layer ff (ff-only per configured team dir, one repo at a time),
    armed AFTER the disabled/throttle/dry-run early-outs so a deliberate skip never
    fires the team fetch — mirroring the bash EXIT-trap ordering.

New beyond bash parity: the personal content overlay (content_dir(), when it
resolves to an explicit separate repo, not the single-repo-layout fallback) gets
the identical strict-safe ff treatment as team layers — same non-fatal stderr-note
contract, gated by the `sync.content` param. Neither this nor the engine sync ever
pushes; "local ahead" has always been report-only in this script. The standing
"push without asking" behavior lives in the np-core-sync SKILL.md's own written
protocol for the human-attended /np-core-sync invocation, not in this module.

Parity-locked (status-message outcome, modulo the embedded UTC timestamp) to the
bash original by tests/mcp/parity/test_sync_parity.sh. stdlib only.
"""
import os
import sys
# self-bootstrap (phase 20b-2): engine/setup holds np_paths, np_bashlib, the config
# files, and the stayed sibling modules; add it so this relocated module resolves them
# whether imported in-process or run standalone. Its own dir (nervepack_engine) is
# already on sys.path[0] when run directly, so moved-sibling imports resolve too.
_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import glob
import io
import os
import subprocess
import sys
import time

import np_bashlib
import np_content
import np_layout
import np_link_skills
import np_toggle


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())   # date -u +%FT%TZ


def _git(target, *args):
    return subprocess.run(np_bashlib.argv(["git", "-C", target, *args]),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True)


def _is_ancestor(target, a, b):
    return _git(target, "merge-base", "--is-ancestor", a, b).returncode == 0


def _count(target, rng):
    r = _git(target, "rev-list", "--count", rng)
    return r.stdout.strip() if r.returncode == 0 else "?"


def _porcelain_count(target):
    out = _git(target, "status", "--porcelain").stdout
    return sum(1 for ln in out.splitlines())


def _is_dirty(target):
    # Refresh the stat cache before trusting diff-index: right after a checkout,
    # reset, or any other index-touching op in the same process/session, git can
    # have stale cached stat info and `diff-index --quiet` reports a false
    # positive until something (e.g. `git status`) forces a real content compare.
    # Observed live during a manual re-onboard: a `git checkout -- <file>` and a
    # `git checkout <branch>` immediately followed by a sync both produced a
    # SKIPPED/DIVERGED status on a tree `git status --short` showed as clean.
    # `update-index --refresh` is the standard remedy and is a no-op on an
    # already-settled tree, so it's safe to run unconditionally.
    _git(target, "update-index", "-q", "--refresh")
    tracked_dirty = _git(target, "diff-index", "--quiet", "HEAD", "--").returncode != 0
    untracked = _git(target, "ls-files", "--others", "--exclude-standard").stdout.strip()
    return tracked_dirty or bool(untracked)


def _ff_only_layer_sync(path, kind):
    """Strict-safe ff-only sync for one layer dir (a team root, or the personal
    content overlay): skip if dirty; otherwise fetch, then ff-merge ONLY when
    local HEAD is behind-or-equal to upstream. `git merge --ff-only @{u}`
    trivially SUCCEEDS when HEAD is instead ahead of (or diverged from)
    upstream -- merging an ancestor is a no-op -- so without the explicit
    ancestor check, "ahead" was silently indistinguishable from "fully synced"
    and never produced its note. Caught while adding the content-layer sync
    (test_content_layer_ahead_is_reported_not_pushed); _team_sync had the
    identical latent gap, untested, and is fixed here too now that both share
    this one function. Non-fatal; stderr notes only. `kind` names the layer in
    the message ("team layer" / "content layer")."""
    if _git(path, "status", "--porcelain").stdout.strip() != "":
        sys.stderr.write("np-core-sync: %s %s has local edits — skipping pull\n" % (kind, path))
        return
    ok = _git(path, "fetch", "--quiet", "origin").returncode == 0
    if ok:
        behind_or_equal = _is_ancestor(path, "HEAD", "@{u}")
        ok = behind_or_equal and _git(path, "merge", "--ff-only", "--quiet", "@{u}").returncode == 0
    if not ok:
        sys.stderr.write("np-core-sync: %s %s not fast-forwarded "
                         "(diverged/ahead/no upstream) — left as-is\n" % (kind, path))


def _team_sync():
    """Optional team layer: keep every configured team checkout current via
    _ff_only_layer_sync. Mirrors bash _np_team_sync. No-op when the `team`
    toggle is off."""
    if not np_toggle.enabled("team"):
        return
    for td in np_content.team_dirs():
        if not td:
            continue
        if _git(td, "rev-parse", "--is-inside-work-tree").returncode != 0:
            continue
        _ff_only_layer_sync(td, "team layer")


def _content_sync():
    """Personal content overlay: the same strict-safe treatment as team layers,
    via _ff_only_layer_sync. No-op when the `sync.content` param is off, or when
    content_dir() is not an EXPLICIT overlay (content_is_explicit() False means
    the single-repo legacy layout, where content_dir() just falls back to the
    engine root itself -- there is no separate repo to sync, and touching it
    would double-process the engine under a second name)."""
    if np_toggle.param("sync.content", "on") != "on":
        return
    if not np_content.content_is_explicit():
        return
    cd = np_content.content_dir()
    if not cd:
        return
    if _git(cd, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return
    _ff_only_layer_sync(cd, "content layer")


def _layout_validity_check():
    """Validate every configured content layer's .nervepack/layout.json. Reuses
    np_layout.resolve, the same check np_doctor runs for the layer-layout
    capability, so a corrupt or invalid manifest gets caught on every sync
    instead of only when someone happens to run the doctor (nervepack#244).
    Non-fatal; a bad manifest prints an stderr note and sync continues -- it
    must not touch the parity-locked status file (personal/team layer outcomes
    are stderr-only, same as _team_sync/_content_sync above)."""
    try:
        roots = np_content.content_layers()
    except Exception:
        return
    for r in roots:
        try:
            np_layout.resolve(r)
        except np_layout.LayoutError as exc:
            sys.stderr.write("np-core-sync: layout manifest invalid in %s: %s\n" % (r, exc))


def _post_ff_steps(target):
    """After a successful fast-forward: relink skills + re-apply hook registration
    (both in-process) and re-run the remaining non-hook [56][0-9]-install-*.sh
    installers from the SYNCED target. All best-effort (bash `|| true` semantics)."""
    try:
        np_link_skills.link(np_dir=target, out=io.StringIO())
    except Exception:
        pass
    # Re-apply hook registration so a pulled change to a hook's registered command
    # (or a new hook row) reaches settings.json — git pull alone updates the scripts
    # on disk but never re-applies them (phase 13: install-hooks, in-process here).
    try:
        import np_hook
        np_hook.install_hooks()
    except Exception:
        pass
    # Re-run the remaining non-hook 5x/6x installers (58-install-mcp.sh +
    # 62-install-scheduled-auth-token.sh post-consolidation) from the SYNCED target,
    # so a pulled change to them re-applies too. Same [56][0-9]-install-*.sh glob as
    # np_onboard's step 2b. Routed through np_bashlib.argv for the Windows lane.
    setup_dir = os.path.join(target, "engine", "setup")
    for f in sorted(glob.glob(os.path.join(setup_dir, "[56][0-9]-install-*.sh"))):
        try:
            subprocess.run(np_bashlib.argv(["bash", f]),
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except OSError:
            pass


def _engine_sync(target, status_file):
    """The defensive engine sync (the 5 cases + not-a-git/fetch-fail). Writes the
    outcome line to the status file and returns it."""
    def write_status(msg):
        try:
            os.makedirs(os.path.dirname(status_file), exist_ok=True)
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass
        return msg

    # `rev-parse --is-inside-work-tree` (not `.git` isdir) so a linked git worktree —
    # where `.git` is a FILE, not a dir — is correctly recognized as a repo. Matches
    # the worktree-correct checks in _team_sync and np_doctor._git_ok. (#172)
    if _git(target, "rev-parse", "--is-inside-work-tree").returncode != 0:
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
            _post_ff_steps(target)
            sh = _git(target, "rev-parse", "--short", "HEAD").stdout.strip()
            return write_status("np-core-sync: %s — fast-forwarded %s commit(s) to %s" % (_now(), pulled, sh))
        return write_status("np-core-sync: %s — ff-only merge failed: %s" % (_now(), ff.stderr.strip()))
    # diverged -> never auto-resolve
    return write_status("np-core-sync: %s — DIVERGED (%s local-only, %s remote-only commits). "
                        "Resolve: cd ~/Code/nervepack && git pull --rebase --autostash"
                        % (_now(), _count(target, "origin/main..HEAD"), _count(target, "HEAD..origin/main")))


def sync(mode="backup", verbose=False):
    """Run the defensive sync; return the single outcome line (matching what the bash
    script echoes / writes to the status file). `exit` mode always syncs; `backup`
    mode is throttled by sync.interval. On a real engine-sync path (past the early
    exits) the team layer is fast-forwarded too."""
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

    # Past the deliberate early-outs (disabled / throttle / dry-run): the team pull
    # is now armed. Every real engine-sync outcome below — including not-a-git and a
    # status write — fires it, but the early skips above never did (they returned).
    target = os.environ.get("NP_SYNC_TARGET") or os.path.join(_home(), "Code", "nervepack")
    status_file = os.environ.get("NP_SYNC_STATUS") or os.path.join(
        _home(), ".cache", "np-core-sync-status")
    outcome = _engine_sync(target, status_file)
    _team_sync()
    _content_sync()
    _layout_validity_check()
    return outcome


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = sys.argv[1:]
    mode = "exit" if "exit" in args else "backup"
    verbose = "--verbose" in args
    # The engine-sync outcome always lands in the status file; echo it on stdout too
    # so the CLI/skill/parity harness see it (the bash echoes only under --verbose,
    # but its callers read the status file — the parity harness normalizes both).
    sys.stdout.write(sync(mode, verbose) + "\n")
