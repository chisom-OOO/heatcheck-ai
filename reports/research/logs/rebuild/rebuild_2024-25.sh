#!/usr/bin/env bash
# Rebuild the sealed 2024-25 season on a fresh Linux/macOS machine and check it against the frozen seal.
# Needs: git, curl, sha256sum (macOS: shasum -a 256), Python 3.13, uv (or pip). Does NOT run the confirmatory test.
set -euo pipefail
WORK=${WORK:-$PWD/hc-rebuild}; mkdir -p "$WORK"; cd "$WORK"
COMMIT=${COMMIT:-e7e885763cc1f787d451b76afc7dafe3d1574a34}
UP=https://raw.githubusercontent.com/shufinskiy/nba_data/46488f0f8e1cab58fc1256511ea808166a443a15/datasets

# 1. code at the exact commit
git clone -q --branch research/r001-guard-fixes https://github.com/chisom-OOO/heatcheck-ai repo
git -C repo checkout -q "$COMMIT"
H=repo/handoff/research-20261107

# 2. pinned environment (versions recorded in the evidence)
uv venv -q -p 3.13 venv
uv pip install -q -p venv/bin/python numpy==2.5.3 pandas==3.0.5 scipy==1.18.1 scikit-learn==1.9.1 pytest

# 3. pinned upstream archives (sha256 checked; the build also checks bytes and git blob id)
mkdir -p up/datasets up/extracted
echo 46488f0f8e1cab58fc1256511ea808166a443a15 > up/COMMIT
curl -sSfL -o up/datasets/cdnnba_2024.tar.xz   "$UP/cdnnba_2024.tar.xz"
curl -sSfL -o up/datasets/nbastats_2024.tar.xz "$UP/nbastats_2024.tar.xz"
( cd up/datasets && sha256sum -c - <<'SUMS'
35a82e6b29821adb22b8474dea8c51e08847d8e00690d1d5ffde7d000e0087d1  cdnnba_2024.tar.xz
8f370da00ad0a6d4157921bd161d56ea32647a165d906516f2b36384a6a4989a  nbastats_2024.tar.xz
SUMS
)
for f in up/datasets/*.tar.xz; do tar -xJf "$f" -C up/extracted; done

# 4. build (prints counts and hashes only)
venv/bin/python -I $H/scripts/build_confirmatory.py up data2024 up/extracted

# 5. compare with the frozen seal (reads hashes only; reserves nothing)
venv/bin/python -I - "$H" data2024 <<'PY'
import json, sys
from pathlib import Path
h, data = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(h / "src"))
from heatcheck import store
fam = json.loads((h / "evidence/confirmatory-2024-25/family.json").read_text())
got = store.logical_table_hashes(data, store.SEASON_TABLES)
for k, v in fam["sealed_data_hashes"].items():
    print(f"{k:12s} {'MATCH' if got[k] == v else 'DIFF '} {got[k]}")
print("SEAL MATCH" if got == fam["sealed_data_hashes"] else "SEAL MISMATCH"); sys.exit(0 if got == fam["sealed_data_hashes"] else 1)
PY

# 6. seal-binding tests against this build (optional; ~1 min)
( cd $H && HC_DATA_2024="$WORK/data2024" ../../../venv/bin/python -m pytest -q -p no:cacheprovider -rs \
    tests/test_confirmatory.py -k real_2024 )
