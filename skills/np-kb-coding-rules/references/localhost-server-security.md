# Localhost server security — implementation details

For Rule 10 of [[np-kb-coding-rules]]: the "how" behind each minimum-bar item.

## CSRF guard (every mutating route)

Require loopback `Host`, loopback `Origin` when sent, **and** a custom header the page
sets. A cross-origin form POST cannot add a custom header without triggering a CORS
preflight — which you refuse; return `403` on any mutating request lacking the header.

## Path-sanitize (any FS-mapped path)

Use `realpath` to resolve the requested path and verify it falls under the served root.
Block `../` traversal.

Worked example + stdlib mechanics: `engine/setup/np-dashboard-server.py` and [[python-http-server]] (`sources/python/`).
