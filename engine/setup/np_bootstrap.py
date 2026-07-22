"""Python port of the one-time toolchain-baseline bootstrap scripts (phase 7 of
the bash->Python CLI consolidation -- content overlay spec
2026-07-15-nervepack-python-cli-consolidation-design.md): install-apt-baseline,
install-brew-baseline, install-rustup, install-claude-plugins, prewarm-serena,
install-pii-deps, install-vscode-extensions. Dispatched via `cli.py setup <name>`.

These are rarely-run, real-system-mutating, interactive-machine-setup scripts
(no CI coverage on the bash originals beyond a syntax/portability scan) --
every external call goes through the injectable `run_fn`/`which_fn` seams so
tests can verify the exact command sequence without touching a real
apt/brew/rustup/claude/code/pip installation.
"""
import os
import shutil
import subprocess
import sys


def _default_run(cmd, **kwargs):
    kwargs.setdefault("check", False)
    return subprocess.run(cmd, **kwargs)


def _default_which(name):
    return shutil.which(name)


def _print_versions(run_fn, specs):
    """specs: list of (cmd_list, label) -- best-effort, never raises."""
    for cmd, label in specs:
        try:
            result = run_fn(cmd, capture_output=True, text=True)
            out = (result.stdout or "").splitlines()
            print(out[0] if out else "")
        except Exception:
            print("%s: (unavailable)" % label)


# --- install-apt-baseline (Linux) --------------------------------------------

_APT_PACKAGES = [
    "git", "gh", "jq", "nodejs", "npm", "python3-pip", "python3-venv", "pipx",
    "golang-go", "build-essential", "curl", "ca-certificates", "cron",
]


def install_apt_baseline(run_fn=None, which_fn=None):
    run_fn = run_fn or _default_run
    which_fn = which_fn or _default_which
    if not which_fn("sudo"):
        print("sudo is required")
        return 1
    run_fn(["sudo", "apt", "update"], check=True)
    run_fn(["sudo", "apt", "install", "-y"] + _APT_PACKAGES, check=True)
    print("\nInstalled versions:")
    _print_versions(run_fn, [
        (["git", "--version"], "git"), (["gh", "--version"], "gh"),
        (["jq", "--version"], "jq"), (["node", "--version"], "node"),
        (["npm", "--version"], "npm"), (["python3", "--version"], "python3"),
        (["go", "version"], "go"),
    ])
    return 0


# --- install-brew-baseline (macOS) -------------------------------------------

def install_brew_baseline(run_fn=None, which_fn=None):
    run_fn = run_fn or _default_run
    which_fn = which_fn or _default_which
    if not which_fn("brew"):
        print("Homebrew is required. Install it from https://brew.sh then re-run.")
        return 1
    # git + a C toolchain ship with the Xcode Command Line Tools on macOS; brew
    # only owns what's left (Python is deliberately NOT brewed -- uv manages it).
    if not which_fn("git"):
        run_fn(["xcode-select", "--install"])
    run_fn(["brew", "install", "gh", "jq", "node", "go", "uv"], check=True)
    run_fn(["uv", "python", "install"], check=True)
    print("\nInstalled versions:")
    _print_versions(run_fn, [
        (["git", "--version"], "git"), (["gh", "--version"], "gh"),
        (["jq", "--version"], "jq"), (["node", "--version"], "node"),
        (["npm", "--version"], "npm"), (["go", "version"], "go"),
        (["uv", "--version"], "uv"),
    ])
    return 0


# --- install-rustup -----------------------------------------------------------

def install_rustup(run_fn=None, which_fn=None, install_fn=None):
    run_fn = run_fn or _default_run
    which_fn = which_fn or _default_which
    if which_fn("rustup"):
        result = run_fn(["rustup", "--version"], capture_output=True, text=True)
        print("rustup already installed: %s" % (result.stdout or "").strip())
        return 0

    def _default_install():
        run_fn(["sh", "-c",
                "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"],
               check=True)

    (install_fn or _default_install)()
    run_fn(["rustc", "--version"])
    run_fn(["cargo", "--version"])
    return 0


# --- install-claude-plugins ---------------------------------------------------

_PLUGINS = [
    "superpowers", "code-review", "commit-commands", "security-guidance", "frontend-design",
    "typescript-lsp", "pyright-lsp", "gopls-lsp", "rust-analyzer-lsp",
    "github", "context7", "playwright", "serena", "stripe",
]
# Installed but left OFF by default (opt in per-project) -- see the bash
# original's comment on global-enable's subagent MCP-server fan-out cost.
_DEFAULT_OFF_PLUGINS = ["serena"]


def install_claude_plugins(run_fn=None, which_fn=None):
    run_fn = run_fn or _default_run
    which_fn = which_fn or _default_which
    if not which_fn("claude"):
        print("claude CLI not found on PATH")
        return 1
    if not which_fn("git"):
        print("git is required (plugin install uses git clone). Run install-apt-baseline first.")
        return 1

    failed = []
    for p in _PLUGINS:
        print("==> %s" % p)
        result = run_fn(["claude", "plugin", "install", "%s@claude-plugins-official" % p])
        if result.returncode != 0:
            failed.append(p)

    for p in _DEFAULT_OFF_PLUGINS:
        print("==> disabling %s globally (opt in per-project instead)" % p)
        run_fn(["claude", "plugin", "disable", "%s@claude-plugins-official" % p])

    print()
    if failed:
        print("Failed: %s" % " ".join(failed))
        return 1
    print("All plugins installed.")
    return 0


# --- prewarm-serena ------------------------------------------------------------

# Must match the source string in serena's .mcp.json exactly.
_SERENA_SRC = "git+https://github.com/oraios/serena"


def prewarm_serena(run_fn=None, which_fn=None):
    run_fn = run_fn or _default_run
    which_fn = which_fn or _default_which
    if not which_fn("uvx"):
        print("uvx not found on PATH. Serena launches via uv, not pipx.")
        print("Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh")
        print("(see np-env-ubuntu-claude-dev-setup), then re-run this step.")
        return 1
    print("==> Pre-warming Serena (%s) -- first run clones + builds, please wait..." % _SERENA_SRC)
    result = run_fn(["uvx", "--from", _SERENA_SRC, "serena", "--help"])
    if result.returncode != 0:
        return 1
    print("\nSerena pre-warmed. Restart Claude Code so it connects and the serena__* tools appear.")
    return 0


# --- install-pii-deps ----------------------------------------------------------

def install_pii_deps(run_fn=None):
    run_fn = run_fn or _default_run
    r1 = run_fn([sys.executable, "-m", "pip", "install", "presidio-analyzer", "presidio-anonymizer"])
    if r1.returncode != 0:
        return 1
    r2 = run_fn([sys.executable, "-m", "spacy", "download", "en_core_web_lg"])
    return 0 if r2.returncode == 0 else 1


# --- install-vscode-extensions -------------------------------------------------

_VSCODE_EXTENSIONS = [
    "anthropic.claude-code",
    "foam.foam-vscode", "yzhang.markdown-all-in-one", "davidanson.vscode-markdownlint",
    "bierner.markdown-mermaid", "pomdtr.excalidraw-editor",
    "juanallo.vscode-dependency-cruiser",
    "dbaeumer.vscode-eslint", "esbenp.prettier-vscode",
    "ms-python.python", "ms-python.vscode-pylance", "charliermarsh.ruff",
    "golang.go",
    "rust-lang.rust-analyzer", "tamasfe.even-better-toml",
    "redhat.vscode-yaml",
    "eamodio.gitlens", "mhutchie.git-graph",
    "usernamehw.errorlens", "editorconfig.editorconfig",
    "streetsidesoftware.code-spell-checker", "gruntfuggly.todo-tree",
    "pkief.material-icon-theme",
    "ms-playwright.playwright",
]

_VSCODE_SETTINGS_JSON = """{
  "editor.formatOnSave": true,
  "editor.tabSize": 2,
  "editor.rulers": [100],
  "editor.bracketPairColorization.enabled": true,
  "editor.guides.bracketPairs": "active",
  "editor.linkedEditing": true,
  "editor.inlineSuggest.enabled": true,
  "editor.suggestSelection": "first",
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true,
  "files.trimFinalNewlines": true,
  "files.eol": "\\n",

  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.tabSize": 4,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "[javascript]": { "editor.defaultFormatter": "esbenp.prettier-vscode" },
  "[javascriptreact]": { "editor.defaultFormatter": "esbenp.prettier-vscode" },
  "[typescript]": { "editor.defaultFormatter": "esbenp.prettier-vscode" },
  "[typescriptreact]": { "editor.defaultFormatter": "esbenp.prettier-vscode" },
  "[json]": { "editor.defaultFormatter": "esbenp.prettier-vscode" },
  "[jsonc]": { "editor.defaultFormatter": "esbenp.prettier-vscode" },
  "[yaml]": { "editor.defaultFormatter": "redhat.vscode-yaml" },
  "[go]": {
    "editor.defaultFormatter": "golang.go",
    "editor.tabSize": 4,
    "editor.insertSpaces": false,
    "editor.codeActionsOnSave": { "source.organizeImports": "explicit" }
  },
  "[rust]": {
    "editor.defaultFormatter": "rust-lang.rust-analyzer",
    "editor.tabSize": 4
  },
  "[toml]": { "editor.defaultFormatter": "tamasfe.even-better-toml" },
  "[markdown]": {
    "editor.wordWrap": "on",
    "editor.formatOnSave": false,
    "editor.quickSuggestions": { "comments": "off", "strings": "off", "other": "off" }
  },

  "python.analysis.typeCheckingMode": "basic",
  "python.analysis.autoImportCompletions": true,

  "rust-analyzer.check.command": "clippy",
  "rust-analyzer.cargo.features": "all",

  "go.useLanguageServer": true,
  "go.lintTool": "golangci-lint",
  "gopls": { "ui.semanticTokens": true },

  "eslint.run": "onSave",
  "typescript.updateImportsOnFileMove.enabled": "always",
  "javascript.updateImportsOnFileMove.enabled": "always",

  "git.confirmSync": false,
  "git.enableSmartCommit": true,
  "git.autofetch": true,

  "gitlens.codeLens.enabled": false,
  "gitlens.currentLine.enabled": false,

  "errorLens.enabledDiagnosticLevels": ["error", "warning"],
  "errorLens.gutterIconsEnabled": true,

  "todo-tree.general.tags": ["TODO", "FIXME", "BUG", "HACK", "NOTE", "XXX"],
  "todo-tree.highlights.defaultHighlight": {
    "type": "tag",
    "foreground": "white",
    "background": "#ff8c00"
  },

  "cSpell.enabled": true,
  "cSpell.diagnosticLevel": "Hint",

  "foam.openDailyNote.directory": "daily-notes",
  "foam.files.defaultExtension": "md",

  "workbench.iconTheme": "material-icon-theme",
  "workbench.editor.enablePreview": false,
  "workbench.list.smoothScrolling": true,

  "terminal.integrated.scrollback": 10000,
  "terminal.integrated.copyOnSelection": true,

  "telemetry.telemetryLevel": "off",
  "redhat.telemetry.enabled": false,
  "update.showReleaseNotes": false,

  "explorer.confirmDragAndDrop": false,
  "explorer.confirmDelete": true,

  "search.exclude": {
    "**/node_modules": true,
    "**/dist": true,
    "**/.next": true,
    "**/target": true,
    "**/.venv": true,
    "**/__pycache__": true
  }
}
"""


def install_vscode_extensions(run_fn=None, which_fn=None, settings_path=None):
    run_fn = run_fn or _default_run
    which_fn = which_fn or _default_which
    if not which_fn("code"):
        print("VSCode 'code' CLI not found on PATH.")
        print("Install VSCode first: https://code.visualstudio.com/docs/setup/linux")
        return 1

    failed = []
    for ext in _VSCODE_EXTENSIONS:
        print("==> %s" % ext)
        result = run_fn(["code", "--install-extension", ext],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            failed.append(ext)

    settings_path = settings_path or os.path.join(
        os.environ.get("HOME") or os.path.expanduser("~"), ".config", "Code", "User", "settings.json")
    if not os.path.isfile(settings_path):
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as fh:
            fh.write(_VSCODE_SETTINGS_JSON)
        print("Wrote default settings.json to %s" % settings_path)
    else:
        print("settings.json already exists; leaving it alone.")

    print()
    if failed:
        print("Failed: %s" % " ".join(failed))
        return 1
    print("VSCode setup complete.")
    return 0
