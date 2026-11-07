"""E-001 A3: changing one byte of any raw payload makes validation and replay fail."""

from __future__ import annotations

import shutil

import pytest
from conftest import BUNDLE

from heatcheck.contracts.bundle import BundleError, load_bundle
from heatcheck.markets.adapters.common import AdapterError
from heatcheck.markets.adapters.replay import read_raw, replay_bundle

RAW_FILES = sorted(p.name for p in (BUNDLE / "raw").iterdir())


def test_bundle_has_five_raw_payloads():
    assert len(RAW_FILES) == 5


@pytest.mark.parametrize("name", RAW_FILES)
def test_a3_one_changed_byte_fails(tmp_path, name, no_network):
    copy = tmp_path / "e001"
    shutil.copytree(BUNDLE, copy)
    target = copy / "raw" / name
    data = bytearray(target.read_bytes())
    i = data.index(b'"') + 1  # inside the first key: keeps the change small and visible
    data[i] = ord("X") if data[i] != ord("X") else ord("Y")
    target.write_bytes(bytes(data))

    with pytest.raises(BundleError, match="hash mismatch"):
        load_bundle(copy)
    with pytest.raises(AdapterError):
        replay_bundle(copy)


@pytest.mark.parametrize("name", RAW_FILES)
def test_replay_itself_checks_each_raw_hash(tmp_path, name):
    """Replay does not rely on the validator: a still-parseable change is caught by hash."""
    copy = tmp_path / "e001"
    shutil.copytree(BUNDLE, copy)
    target = copy / "raw" / name
    target.write_bytes(target.read_bytes() + b"\n")  # valid JSON, different bytes
    with pytest.raises(AdapterError, match="does not match its sha256"):
        read_raw(copy, target.stem)
