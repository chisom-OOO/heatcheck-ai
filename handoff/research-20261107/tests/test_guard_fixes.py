"""Regression tests for reviewer findings RV-R1 (final step bound to its data), RV-R2 (record-id
canonicalisation before exposure checks) and RV-R4/R5 (code-hash coverage, sensitivity reporting).

Unit tests use synthetic ids and run anywhere with fcntl. The real-data tests need the built dataset
(HC_DATA or data/run1) and are SKIPPED otherwise: report a skip as NOT_RUN, never as a pass."""
import importlib.util
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from heatcheck import store
from heatcheck.custodian import Custodian, ExposureRefused, canonical_record_id
from heatcheck.util import frame_hash

ROOT = Path(__file__).resolve().parents[1]
IDS = ["0022300901", "0022300902", "0022300903"]


def _res(c, fam="F1", ids=IDS, code="c", plan="p", inp=None):
    return c.reserve(family_id=fam, epoch_id=f"E-{fam}", plan_hash=plan, code_hash=code,
                     record_ids=ids, input_hash=inp)


# --------------------------------------------------------------------------- RV-R2
@pytest.mark.parametrize("raw,canon", [("0022300901", "nba:0022300901"), ("nba:0022300901", "nba:0022300901"),
                                       ("22300901", "nba:0022300901"), ("syn:g1", "syn:g1")])
def test_canonical_record_id(raw, canon):
    assert canonical_record_id(raw) == canon


@pytest.mark.parametrize("bad", [" 0022300901", "0022300901\n", "", "nba:abc", "nba:00223009011", 22300901,
                                 "00223\x0000901"])
def test_malformed_record_id_refused(bad):
    with pytest.raises(ExposureRefused):
        canonical_record_id(bad)


def test_respelled_ids_are_the_same_job_retry(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    r1 = _res(c)
    r2 = _res(c, ids=["nba:" + i for i in reversed(IDS)])
    assert r2["retry"] and r2["receipt_id"] == r1["receipt_id"]


def test_respelled_ids_cannot_reopen_under_new_family(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    _res(c)
    with pytest.raises(ExposureRefused):
        _res(c, fam="F2", ids=["nba:0022300902"])


def test_legacy_raw_id_ledger_is_canonicalised(tmp_path):
    """A pre-fix ledger line (bare ids, raw job_hash, no input_hash) still blocks re-spelled ids."""
    path = tmp_path / "l.jsonl"
    path.write_text(json.dumps({"type": "reserve", "receipt_id": "legacy", "family_id": "F1", "epoch_id": "E-F1",
                                "plan_hash": "p", "code_hash": "c", "job_hash": "raw", "record_ids": IDS,
                                "at_utc": "2026-11-07T15:22:56.888622Z"}) + "\n")
    c = Custodian(path)
    with pytest.raises(ExposureRefused):
        _res(c, fam="F2", ids=["22300903"])
    assert _res(c, ids=["nba:" + i for i in IDS])["receipt_id"] == "legacy"


# --------------------------------------------------------------------------- RV-R1 (custodian level)
def test_retry_with_different_input_is_refused(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    r1 = _res(c, inp="A")
    assert _res(c, inp="A")["receipt_id"] == r1["receipt_id"]
    with pytest.raises(ExposureRefused):
        _res(c, inp="B")
    with pytest.raises(ExposureRefused):
        _res(c, inp=None)


def test_legacy_reservation_binds_on_first_retry(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    r1 = _res(c)                        # pre-binding style: no input_hash
    assert _res(c, inp="A")["input_hash_bound"] == "A"
    assert [e["type"] for e in c.history(r1["receipt_id"])] == ["reserve", "bind"]
    with pytest.raises(ExposureRefused):
        _res(c, inp="B")


def _replay(c, rid, fam="F1", ids=IDS, am="am1", code="c2", inp="A"):
    return c.replay(receipt_id=rid, family_id=fam, epoch_id=f"E-{fam}", record_ids=ids,
                    amendment_hash=am, code_hash=code, input_hash=inp)


def test_replay_rules(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    rid = _res(c, inp="A")["receipt_id"]
    with pytest.raises(ExposureRefused, match="spent"):
        _replay(c, rid)
    c.spend(rid)
    with pytest.raises(ExposureRefused):
        _replay(c, rid, ids=IDS[:2])                 # not the original records
    with pytest.raises(ExposureRefused):
        _replay(c, rid, inp="B")                     # data differ from the bound input
    with pytest.raises(ExposureRefused):
        _replay(c, "unknown")
    first = _replay(c, rid)
    assert not first["retry"] and _replay(c, rid)["replay_id"] == first["replay_id"]
    with pytest.raises(ExposureRefused):             # a replay never reopens the records
        _res(c, fam="F2", ids=IDS)


def test_replay_of_legacy_receipt_binds_its_input(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    rid = _res(c)["receipt_id"]; c.spend(rid)
    assert _replay(c, rid, inp="A")["original_input_binding"] == "NONE_PREDATES_BINDING"
    with pytest.raises(ExposureRefused):
        _replay(c, rid, am="am2", code="c3", inp="B")


# --------------------------------------------------------------------------- stored-table hashes
def test_logical_frame_round_trip(tmp_path):
    df = pd.DataFrame({"game_id": ["0022300002", "0022300001"],
                       "tip_utc": pd.to_datetime(["2023-10-24T23:30:00.5Z", "2023-10-25T02:00:00Z"], utc=True,
                                                format="ISO8601"),
                       "neutral_site": [True, False], "team_id": pd.array([1610612737, None], dtype="Int64"),
                       "x": [1.5, float("nan")]})
    store.publish(tmp_path / "public.sqlite", {"games": df})
    back = store.logical_frame(store.read(tmp_path / "public.sqlite", "games"))
    assert frame_hash(back, ["game_id"]) == frame_hash(df, ["game_id"])


# --------------------------------------------------------------------------- final() on real data
DATA = Path(os.environ.get("HC_DATA", ROOT / "data/run1"))
real = pytest.mark.skipif(not (DATA / "public.sqlite").exists(), reason="NOT_RUN: dataset not built")


def _gp():
    spec = importlib.util.spec_from_file_location("gp_under_test", ROOT / "scripts/game_prediction.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _evidence_copy(tmp_path, with_amendments=True):
    out = tmp_path / "ev"
    shutil.copytree(ROOT / "evidence", out)
    if not with_amendments:
        for p in out.glob("claim_plan_GP.amendment-*.json"):
            p.unlink()
    return out


def _data_copy(tmp_path):
    d = tmp_path / "data"; d.mkdir()
    (d / "public.sqlite").symlink_to(DATA / "public.sqlite")
    shutil.copy(DATA / "restricted_labels.sqlite", d / "restricted_labels.sqlite")
    shutil.copy(DATA / "manifest.json", d / "manifest.json")
    return d


@real
def test_stored_tables_hash_to_the_frozen_plan():
    plan = json.loads((ROOT / "evidence/claim_plan_GP.json").read_text())
    assert store.logical_table_hashes(DATA) == plan["data_hashes"]


@real
def test_final_refuses_changed_labels_and_leaves_ledger_untouched(tmp_path):
    gp = _gp(); out = _evidence_copy(tmp_path); data = _data_copy(tmp_path)
    con = sqlite3.connect(data / "restricted_labels.sqlite")
    con.execute("UPDATE game_labels SET home_win = 1 - home_win WHERE game_id IN "
                "(SELECT game_id FROM game_labels WHERE game_id >= '0022300902' ORDER BY game_id LIMIT 40)")
    con.commit(); con.close()
    before = (out / "custodian_ledger.jsonl").read_bytes()
    with pytest.raises(gp.FinalRefused, match="game_labels"):
        gp.final(data, out)
    assert (out / "custodian_ledger.jsonl").read_bytes() == before


@real
def test_final_refuses_changed_code_without_amendment(tmp_path):
    gp = _gp(); out = _evidence_copy(tmp_path, with_amendments=False)
    before = (out / "custodian_ledger.jsonl").read_bytes()
    with pytest.raises(gp.FinalRefused, match="amendment"):
        gp.final(DATA, out)
    assert (out / "custodian_ledger.jsonl").read_bytes() == before


@real
def test_final_refuses_edited_plan(tmp_path):
    gp = _gp(); out = _evidence_copy(tmp_path)
    plan = json.loads((out / "claim_plan_GP.json").read_text())
    plan["practical_effect_floor"] = 0.0
    (out / "claim_plan_GP.json").write_text(json.dumps(plan, indent=2))
    with pytest.raises(gp.FinalRefused, match="canonical_plan_hash"):
        gp.final(DATA, out)
