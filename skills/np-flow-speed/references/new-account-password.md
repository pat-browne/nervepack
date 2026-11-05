# New-account password (credentials carve-out)

Speed mode generates a new-account password and never asks for or shows it. Run
`new-account-secret.sh ITEM USERNAME URL --generate` from [[np-env-secrets-refresh]]
(`scripts/new-account-secret.sh`) in a real terminal with the vault unlocked. It stores
the password in Bitwarden and copies it to the clipboard. Never print or log the value.
If the script exits non-zero, such as a locked vault or an existing item, stop and report
its message. On success, tell the user to paste the clipboard into the form and submit it.
