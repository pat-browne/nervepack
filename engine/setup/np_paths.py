"""Canonical filesystem anchors for the nervepack engine.

Resolved from THIS module's own stable location, NOT from each caller's
`__file__`. Library modules reference shared config / data / helper scripts via
these anchors (`SETUP_DIR`, `ENGINE_DIR`, `REPO_ROOT`) instead of computing
`os.path.join(_HERE, "toggles.conf")` locally — which decouples a module's own
file location from where its config lives. That decoupling is what lets the
library modules relocate (e.g. into `engine/nervepack_engine/`) without breaking
config resolution: `np_paths.SETUP_DIR` still points at `engine/setup/` no matter
where the importing module sits.

This module intentionally lives in `engine/setup/` — it anchors TO that dir (the
engine's config/data + helper-script home). A relocated module imports it flat
and still gets the right `SETUP_DIR`. Stdlib only.
"""
import os

# engine/setup — where toggles.conf, hooks.manifest, allowlist-entries.txt,
# toggle-schema.json, and the np-*.py helper scripts live.
SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
# engine/ — parent of setup/ and of nervepack_engine/.
ENGINE_DIR = os.path.dirname(SETUP_DIR)
# the repo root (contains engine/, dashboard/, skills/, docs/, …). This is the
# `NP_DIR` default and what np_toggle/np_content/np_doctor mean by "the repo".
REPO_ROOT = os.path.dirname(ENGINE_DIR)
