#!/usr/bin/env bash
# Verify bundled upstream archives against pinned SHA-256, extract them, build the canonical dataset.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd raw/repo/datasets && sha256sum -c ../SHA256SUMS)
mkdir -p raw/extracted
for f in raw/repo/datasets/*.tar.xz; do tar -xJf "$f" -C raw/extracted; done
python3 -I scripts/build_dataset.py raw/repo data/run1 raw/extracted
