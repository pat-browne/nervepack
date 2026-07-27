#!/usr/bin/env python3
"""Shared frontmatter + env-int helpers for the skill-maintenance modules.

`_int_env` and a first-block `---` frontmatter field reader were copy-pasted
(with only the missing-value default differing) across np_skill_budget.py,
np_skill_validate.py, and np_graduation_detect.py. Centralizing them keeps the
delimiter/parse convention in one place so the budget detector, the split-gate,
and the graduation scan can't silently drift apart. (#176) Pure stdlib.
"""
import os


def int_env(name, default):
    """os.environ[name] parsed as int, or `default` on missing/non-integer."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def field(text, name, default=None):
    """Value of frontmatter `<name>:` in the first `---`…`---` block, stripped;
    `default` if the text has no frontmatter block or the field is absent.
    Callers that want '' on absence pass default=""."""
    if not text.startswith("---"):
        return default
    end = text.find("\n---", 3)
    if end == -1:
        return default
    for line in text[3:end].splitlines():
        if line.startswith(name + ":"):
            return line[len(name) + 1:].strip()
    return default
