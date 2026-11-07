"""Reviewer probes of Research's custodian (incoming/research-20261107/src/heatcheck/custodian.py).

Run with HEATCHECK_REVIEW_RESEARCH_SRC=<handoff>/src (needs fcntl, i.e. Linux/macOS).
"""

from __future__ import annotations

import importlib
import multiprocessing as mp
import os
import sys

import pytest

SRC = os.environ.get("HEATCHECK_REVIEW_RESEARCH_SRC")
if not SRC:
    pytest.skip("NOT_RUN: set HEATCHECK_REVIEW_RESEARCH_SRC", allow_module_level=True)
pytest.importorskip("fcntl", reason="NOT_RUN: custodian needs fcntl (Linux/macOS)")
sys.path.insert(0, SRC)
for name in [m for m in sys.modules if m == "heatcheck" or m.startswith("heatcheck.")]:
    del sys.modules[name]  # use the handoff's package, not the repo's heatcheck/
cust = importlib.import_module("heatcheck.custodian")
Custodian, ExposureRefused = cust.Custodian, cust.ExposureRefused

IDS = ["0022300901", "0022300902", "0022300903"]


def _reserve(c, fam, ids, code="c"):
    return c.reserve(family_id=fam, epoch_id=f"E-{fam}", plan_hash="p", code_hash=code,
                     record_ids=ids)


@pytest.mark.parametrize("variant", [
    ["nba:0022300901"], ["22300901"], [" 0022300901"], ["0022300901\n"],
], ids=["nba_prefix", "leading_zeros_dropped", "leading_space", "trailing_newline"])
def test_rv_c1_id_spelling_variant_cannot_reopen(tmp_path, variant):
    c = Custodian(tmp_path / "ledger.jsonl")
    _reserve(c, "F1", IDS)
    with pytest.raises(ExposureRefused):
        _reserve(c, "F2", variant)  # same game 0022300901, spelled differently


def test_rv_c2_truncated_ledger_fails_closed(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _reserve(Custodian(path), "F1", IDS)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])  # crash mid-write
    with pytest.raises(Exception) as exc:
        _reserve(Custodian(path), "F2", IDS)
    assert not isinstance(exc.value, AssertionError)


def _race(path, i, q):
    try:
        _reserve(Custodian(path), f"F{i}", IDS)
        q.put("ok")
    except ExposureRefused:
        q.put("refused")


@pytest.mark.parametrize("method", ["fork", "spawn", "forkserver"])
def test_rv_c3_race_under_each_start_method(tmp_path, method):
    ctx = mp.get_context(method)
    q = ctx.Queue()
    ps = [ctx.Process(target=_race, args=(tmp_path / "l.jsonl", i, q)) for i in range(8)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    res = sorted(q.get(timeout=10) for _ in ps)
    assert res.count("ok") == 1 and res.count("refused") == 7, res


def test_rv_c4_retry_after_spend_returns_same_receipt_and_stays_spent(tmp_path):
    c = Custodian(tmp_path / "ledger.jsonl")
    r1 = _reserve(c, "F1", IDS)
    c.spend(r1["receipt_id"])
    r2 = _reserve(c, "F1", list(reversed(IDS)))
    assert r2["retry"] and r2["receipt_id"] == r1["receipt_id"] and c.is_spent(r1["receipt_id"])


def test_rv_c5_subset_with_same_identity_is_not_a_retry(tmp_path):
    c = Custodian(tmp_path / "ledger.jsonl")
    _reserve(c, "F1", IDS)
    with pytest.raises(ExposureRefused):
        c.reserve(family_id="F1", epoch_id="E-F1", plan_hash="p", code_hash="c",
                  record_ids=IDS[:2])
