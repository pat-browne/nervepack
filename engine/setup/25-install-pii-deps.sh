#!/usr/bin/env bash
# Optional: install Presidio + spaCy for np-pii-filter --mode full.
# Safe to skip — filter degrades gracefully to regex-only without these.
set -euo pipefail
python3 -m pip install presidio-analyzer presidio-anonymizer
python3 -m spacy download en_core_web_lg
