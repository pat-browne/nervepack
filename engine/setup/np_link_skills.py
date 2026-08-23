"""Bash-free port of 30-link-skills.sh — symlink every skill from the engine repo's
skills/, the personal overlay's skills/, AND (when the `team` toggle is on) the team
layer's skills/ into the host skill dir (e.g. ~/.claude/skills), then regenerate
INDEX.md in-process (phase 17 of the bash->Python CLI migration).

Three-layer precedence: engine < personal < team (team wins on a name clash). Safe
to re-run:
  - existing symlinks to the correct target are left alone;
  - a non-symlink at the target path is reported and skipped (no overwrite);
  - dangling symlinks whose target is under any managed source base are pruned;
  - symlinks pointing elsewhere are never touched.

Symlink creation is privilege-gated on the Windows lane: an individual os.symlink
that fails is reported and skipped (never aborts the run) so the INDEX regen — the
host-agnostic half — still happens. stdlib only.
"""
import os
import sys
# self-bootstrap (phase 20b-2): np_toggle/np_content/np_model and the other library
# modules were relocated into engine/nervepack_engine/; add that package dir so this
# script's flat imports of them resolve whether run standalone or imported.
_ENGINE_PKG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nervepack_engine"))
if _ENGINE_PKG not in sys.path:
    sys.path.insert(0, _ENGINE_PKG)

import os
import sys

import np_content
import np_host
import np_generate_index
import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))


def _engine_root(np_dir=None):
    """Same safe resolution as np_generate_index: arg -> NP_DIR -> NERVEPACK ->
    this file's repo root (never an unconditional $HOME/Code/nervepack)."""
    return (np_dir or os.environ.get("NP_DIR") or os.environ.get("NERVEPACK")
            or os.path.dirname(os.path.dirname(_HERE)))


def _overlay_root(engine_root):
    d = np_content.content_dir()
    if not d or np_content.content_origin() == "default":
        return engine_root
    return d


def _bases(engine_root, overlay_root):
    """Ordered source base list: engine, personal, then team (highest-precedence
    LAST so the later-wins upsert makes it override). np_team_dirs lists
    highest-first, so it is iterated in reverse — matching the bash."""
    bases = [os.path.join(engine_root, "skills"), os.path.join(overlay_root, "skills")]
    if np_toggle.enabled("team"):
        for t in reversed(np_content.team_dirs()):
            bases.append(os.path.join(t, "skills"))
    return bases


def link(np_dir=None, out=None):
    """Refresh the host skill-dir symlink set and regenerate INDEX.md. Returns 0."""
    out = out or sys.stdout
    engine_root = _engine_root(np_dir)
    overlay_root = _overlay_root(engine_root)
    bases = _bases(engine_root, overlay_root)
    dst = np_host.skills_dir()
    os.makedirs(dst, exist_ok=True)

    def _is_known_base(path):
        for b in bases:
            if path == b or path.startswith(b + os.sep) or path.startswith(b + "/"):
                return True
        return False

    # Deduped name->dir map across the bases (later/overlay/team wins on a clash).
    names = []
    dirs = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            sd = os.path.join(base, entry)
            if not os.path.isdir(sd):
                continue
            if entry in names:
                dirs[names.index(entry)] = sd
            else:
                names.append(entry)
                dirs.append(sd)

    # Prune pass: remove symlinks in $DST whose target is under a managed base but
    # missing (broken link). Symlinks to external/live targets are never touched.
    try:
        listing = sorted(os.listdir(dst))
    except OSError:
        listing = []
    for entry in listing:
        link_path = os.path.join(dst, entry)
        if not os.path.islink(link_path):
            continue
        target = os.readlink(link_path)
        if _is_known_base(target) and not os.path.exists(link_path):
            try:
                os.unlink(link_path)
                out.write("prune %s (target gone: %s)\n" % (entry, target))
            except OSError:
                pass

    # Link pass: iterate the deduped name->dir map, repointing a link when the
    # overlay/team now overrides what was previously an engine-sourced link.
    for name, skill_dir in zip(names, dirs):
        target = os.path.join(dst, name)
        if os.path.islink(target):
            cur = os.readlink(target)
            if cur == skill_dir:
                out.write("ok    %s (already linked)\n" % name)
                continue
            if _is_known_base(cur):
                try:
                    os.unlink(target)
                except OSError:
                    pass
            else:
                sys.stderr.write("skip  %s (symlink to external target, not repointing: %s)\n" % (name, cur))
                continue
        elif os.path.exists(target):
            sys.stderr.write("skip  %s (real file/dir already at %s)\n" % (name, target))
            continue
        try:
            os.symlink(skill_dir, target)
            out.write("link  %s -> %s\n" % (name, skill_dir))
        except OSError as exc:
            # Privilege-gated on Windows / any FS refusal: report + continue so the
            # INDEX regen below still runs (the host-agnostic half of this step).
            sys.stderr.write("skip  %s (could not create symlink: %s)\n" % (name, exc))

    # Regenerate INDEX.md so it tracks the current skill set (in-process).
    np_generate_index.generate(np_dir=engine_root, out=out)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(link())
