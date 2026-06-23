#!/usr/bin/env bash
# Redact secret-shaped substrings from stdin → stdout. Defense-in-depth on top
# of the summarizer's "no secrets" instruction. Conservative by design: catches
# known token shapes, does not attempt to be exhaustive.
set -euo pipefail
# Byte-process (C locale): a redactor must never choke on binary / invalid-UTF-8
# input. Without this, BSD sed (macOS) aborts with "RE error: illegal byte sequence"
# on non-UTF-8 bytes, defeating the fail-open contract.
export LC_ALL=C
sed -E \
  -e 's/sk-[A-Za-z0-9]{16,}/[REDACTED-SECRET]/g' \
  -e 's/github_pat_[A-Za-z0-9_]{20,}/[REDACTED-SECRET]/g' \
  -e 's/gh[opusr]_[A-Za-z0-9]{20,}/[REDACTED-SECRET]/g' \
  -e 's/AKIA[0-9A-Z]{16}/[REDACTED-SECRET]/g' \
  -e 's/xox[baprs]-[A-Za-z0-9-]{10,}/[REDACTED-SECRET]/g' \
  -e 's/(aws_secret_access_key|AWS_SECRET_ACCESS_KEY)[[:space:]]*[:=][[:space:]]*[A-Za-z0-9\/+]{40}/\1=[REDACTED-SECRET]/g' \
  -e 's/[Bb]earer[[:space:]]+[A-Za-z0-9._-]{12,}/Bearer [REDACTED-SECRET]/g' \
  -e 's/([Pp]assword|[Pp]asswd|[Ss]ecret|[Tt]oken|[Aa]pi[_-]?[Kk]ey)("?[[:space:]]*[:=][[:space:]]*"?)[^[:space:]"]{6,}/\1\2[REDACTED-SECRET]/g' \
  -e 's/eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/[REDACTED-JWT]/g' \
  -e 's/-----BEGIN[ A-Z]*PRIVATE KEY-----/[REDACTED-KEY]/g'
