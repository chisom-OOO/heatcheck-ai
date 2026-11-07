"""Max integration checks for the R-001 bridge (translation only; not a leakage test)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from heatcheck.contracts.bundle import load_bundle  # noqa: E402
from heatcheck.contracts.records import validate_record  # noqa: E402
from heatcheck.contracts.research_bridge import RESEARCH_SRC, harness_builder  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "tests" / "fixtures" / "contracts" / "syn_reference_bundle"
RESEARCH_DATA = Path(os.environ.get("HEATCHECK_RESEARCH_DATA",
                                    ROOT / "data" / "processed" / "research-20261107"))


def test_bridge_loads_research_code_unchanged():
    manifest = json.loads((ROOT / "incoming" / "research-20261107.IMPORT.json").read_text("utf-8"))
    want = {f["path"]: f["sha256"] for f in manifest["imported"]}
    got = hashlib.sha256((RESEARCH_SRC / "features.py").read_bytes()).hexdigest()
    assert got == want["src/heatcheck/features.py"]


def test_bridge_rows_validate_on_reference_events():
    _, recs = load_bundle(REF)
    events = [r for r in recs if r["record_type"] == "EVENT"]
    rows = harness_builder(events)
    assert [r["body"]["target_id"] for r in rows] == ["syn:G0001:shot:e2", "syn:G0001:shot:e3"]
    for r in rows:
        validate_record(r)
        assert not any("assist" in name for name in r["body"]["features"])


def test_real_game_bundle_rebuilds_byte_identically():
    if not (RESEARCH_DATA / "public.sqlite").exists():
        pytest.skip("NOT_RUN: Research canonical build not present (data is not redistributable)")
    if not (ROOT / "data" / "bundles" / "r001-nba-0022300061" / "manifest.json").exists():
        pytest.skip("NOT_RUN: run tools/bridge_r001_game.py first")
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "bridge_r001_game.py"), str(RESEARCH_DATA), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert out.returncode == 0 and out.stdout.startswith("PASS"), out.stdout + out.stderr
