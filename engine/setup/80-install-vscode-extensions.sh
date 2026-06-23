#!/usr/bin/env bash
# Install the curated VSCode extension set and write a default settings.json.
# Idempotent: `code --install-extension` is a no-op when already present, and
# settings.json is only written if missing (so per-machine tweaks survive).
#
# See ~/Code/nervepack/skills/np-env-vscode-setup/SKILL.md for rationale.

set -euo pipefail

if ! command -v code >/dev/null; then
  echo "VSCode 'code' CLI not found on PATH." >&2
  echo "Install VSCode first: https://code.visualstudio.com/docs/setup/linux" >&2
  exit 1
fi

EXTENSIONS=(
  # AI
  anthropic.claude-code

  # Markdown graph (Foam) for ~/Code/nervepack and any notes vault
  foam.foam-vscode
  yzhang.markdown-all-in-one
  davidanson.vscode-markdownlint
  bierner.markdown-mermaid

  # Diagrams: edit Excalidraw (.excalidraw) files; native Mermaid->Excalidraw import
  pomdtr.excalidraw-editor

  # Code dependency graph (needs dependency-cruiser npm pkg in target project)
  juanallo.vscode-dependency-cruiser

  # Language: TS/JS
  dbaeumer.vscode-eslint
  esbenp.prettier-vscode

  # Language: Python
  ms-python.python
  ms-python.vscode-pylance
  charliermarsh.ruff

  # Language: Go
  golang.go

  # Language: Rust
  rust-lang.rust-analyzer
  tamasfe.even-better-toml

  # Data formats
  redhat.vscode-yaml

  # Git
  eamodio.gitlens
  mhutchie.git-graph

  # Quality of life
  usernamehw.errorlens
  editorconfig.editorconfig
  streetsidesoftware.code-spell-checker
  gruntfuggly.todo-tree
  pkief.material-icon-theme

  # Testing / browser
  ms-playwright.playwright
)

failed=()
for ext in "${EXTENSIONS[@]}"; do
  echo "==> $ext"
  if ! code --install-extension "$ext" >/dev/null 2>&1; then
    failed+=("$ext")
  fi
done

# Settings.json — only write if missing. Don't clobber per-machine tweaks.
SETTINGS="$HOME/.config/Code/User/settings.json"
if [[ ! -f "$SETTINGS" ]]; then
  mkdir -p "$(dirname "$SETTINGS")"
  cat > "$SETTINGS" <<'JSON'
{
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
  "files.eol": "\n",

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
JSON
  echo "Wrote default settings.json to $SETTINGS"
else
  echo "settings.json already exists; leaving it alone."
fi

echo
if ((${#failed[@]})); then
  echo "Failed: ${failed[*]}" >&2
  exit 1
fi
echo "VSCode setup complete."
