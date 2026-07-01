# Windows CI: bash + native-Python interop gotchas

Two directions, all `windows-latest`-only, all harness artifacts (not the code's fault).

## A. Driving bash FROM a Windows CI lane (`.sh` tests / `.py` that shells out)

Fix via `engine/setup/tests/_lib/nptest.py` (`u`/`sh`/`bash_eval`) and
`engine/setup/np_bashlib.py` (`argv()`/`u()`) at runtime:
- direct `.sh` exec → `WinError 193` (no shebang loader) — run `["bash", script]`, not `[script]`.
- bare `bash` resolves to `System32\bash.exe` (WSL, no distro), **not** Git-bash — pin the
  suite's own bash via `NP_BASH` (`cygpath -w "$(command -v bash)"`, exported by `run-all.sh`).
- `os.path` backslash/drive paths break `source`/`[[ -d ]]` and don't match `pwd` — convert to
  MSYS `/c/x` form (no-op off Windows). CRLF checkout also bites — pin LF via `.gitattributes`.

## B. Parity-testing native-Windows Python against bash (Git-bash lane)

When you port a bash function to Python and A/B test them for **byte-identical**
stdout under the Git-bash `windows-latest` lane, two more artifacts make *correct*
implementations look broken (real bash-free production has no MSYS in the loop).
Reference port: `np_toggle.py` / `np_content.py` + `tests/mcp/parity/`.

## 1. CRLF — native-Windows Python translates `\n` → `\r\n` on stdout

A Python CLI that does `print(x)` / `sys.stdout.write(x + "\n")` emits `x\r\n` in
text mode on Windows, while bash's `printf '%s\n'` emits `x\n`. So **every** line
differs from bash by a trailing `\r` — even identical non-path values (`env`==`env`
fails `cmp`). Tell-tale: a parity test where the *toggle* half passes (its CLI
emits no newline) but the *content* half fails on every row.

**Fix (at the source, one line):** in the parity CLI's `__main__`,
`if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(newline="\n")`.
Now `\n` stays `\n` on every platform, matching bash. (Alternative: strip `\r`
in the test — worse, it masks the difference instead of making the CLI faithful.)

**Sibling trap — stdout encoding.** If the CLI emits any non-ASCII (e.g. `✓`,
`✗`, em-dash `—`), native-Windows Python defaults stdout to **cp1252**, which
can't encode `✓` — and the failing `sys.stdout.write` drops the **whole** output,
so the parity test sees *zero* Python lines vs N bash lines (bash/Git-bash is
UTF-8). Same fix call, add the encoding: `sys.stdout.reconfigure(encoding="utf-8",
newline="\n")`. Seen in `np_doctor.py` (the report has `✓`/`—`).

## 2. Path dialect — bash speaks POSIX, MSYS-converted Python speaks Windows

Under Git-bash, when bash launches the **native-Windows** Python child, MSYS
path-converts the env vars and argv: bash's own function echoes the POSIX form it
was handed (`/tmp/x`, `/d/a/repo`), but Python receives — and returns — the Windows
form (`C:/Users/RUNNER~1/...`, `D:\a\repo`), including **8.3 short names**
(`RUNNER~1`). Same directory, two dialects → byte-identity is the wrong invariant
for **path-valued** outputs (it still holds for non-path outputs once CRLF is fixed).

**Fixes:**
- Give fixtures a form *both* runtimes resolve to the same location: convert the
  test's temp dir to **mixed Windows form** up front (`cygpath -m` on Windows, no-op
  elsewhere). Then env/config-file fixtures are byte-identical across both runtimes,
  and a config path the native Python couldn't `isdir` (`/tmp/...`) becomes one it can.
- For the one intrinsic case you can't fixture around (a resolver's built-in default
  like the engine root: bash `pwd` POSIX vs Python `__file__`/argv Windows form),
  compare **path outputs by resolved identity** — fold each line through `cygpath -u`
  (accepts both POSIX and backslash-Windows input) and lowercase, then `cmp`. Apply
  this only to path-returning calls; keep non-path outputs byte-compared. No-op off
  Windows (no `cygpath`), where byte-identity holds and must be asserted exactly.
- **URIs/keys built from `os.path.relpath` — normalize to `/` at construction.** A
  resource URI, cache key, or any identifier that concatenates a relpath is a path-dialect
  bug in disguise: `os.path.relpath` yields backslashes on Windows, so
  `f"nervepack://wiki/{rel}"` emits `nervepack://wiki/topics\foo\bar` on the Git-bash lane
  while passing on Linux (`os.sep == "/"`). Fix at the point of construction —
  `rel.replace(os.sep, "/")` — so the identifier is forward-slash on every OS. This is the
  *emit-a-stable-string* sibling of the resolved-identity compare above: the value itself
  must be normalized, not merely compared loosely. Real miss: `np-mcp-server.py`
  `list_resources()` (the recursive `wiki/**/*.md` glob) — green on Linux, red on the
  **required** Windows suite until normalized.

## 3. The bash-free lane proves *independence*, parity proves *equivalence*

Parity tests **need bash** (they compare against it), so they run on Linux + the
Git-bash lane, never the bash-free lane. To prove the ported surface needs no bash,
add a separate test that makes bash unreachable for the server child (`NP_BASH` →
a path that doesn't exist) and asserts only the ported read/gate surface answers;
run it on a `windows-latest` lane with Git for Windows stripped from `PATH`
(`$env:PATH = ($env:PATH -split ';' | Where-Object { $_ -notmatch '\\Git\\' }) -join ';'`).
Keep that lane **informational** until the port milestone completes (§5).
Reference: `tests/mcp/test_bashfree.py`.
