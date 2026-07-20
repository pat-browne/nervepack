"""Ported lifecycle-hook implementations. Each module exposes a `run(payload_text,
**kwargs)` function taking the raw stdin payload text; `cli.py` dispatches to these
by name."""
