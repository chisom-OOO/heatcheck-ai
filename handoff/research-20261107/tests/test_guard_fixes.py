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


# --------------------------------------------------------------------------- ruling: every id maps to its game
from heatcheck.custodian import exposure_key  # noqa: E402


@pytest.mark.parametrize("rid,game", [
    ("0022300589", "nba:0022300589"), ("SHOT:0022300589:3012500", "nba:0022300589"),
    ("GAME:0022300589", "nba:0022300589"), ("nba:0022300589:412:r1", "nba:0022300589"),
    ("SHOT:0022300589:3012500:preshot/1", "nba:0022300589"), ("SHOT:nba:22300589:7", "nba:0022300589"),
    ("syn:g1", "syn:g1"), ("SHOT:syn:g1:5", "syn:g1")])
def test_exposure_key_maps_record_to_game(rid, game):
    assert exposure_key(rid) == game


@pytest.mark.parametrize("bad", ["SHOT:22300589:7", "nba-team:1610612737", "x:0022300001:0022300002",
                                 "free-text", "SHOT:syn:"])
def test_exposure_key_refuses_unmappable_or_ambiguous(bad):
    with pytest.raises(ExposureRefused):
        exposure_key(bad)


def test_shot_level_family_over_reserved_final_games_is_refused(tmp_path):
    """Ruling 2026-11-07: a shot-level family over reserved final games must be refused."""
    c = Custodian(tmp_path / "l.jsonl")
    _res(c, fam="GAME-FAMILY", ids=IDS)                              # game-level reservation (bare ids)
    for shots in (["SHOT:0022300902:3012500", "SHOT:0022300902:3012600"],
                  ["SHOT:nba:0022300903:77"], ["nba:0022300901:412:r1"]):
        with pytest.raises(ExposureRefused):
            _res(c, fam="SHOT-FAMILY", ids=shots)
    assert _res(c, fam="OTHER", ids=["SHOT:0022300904:1"])["exposed_games"] == ["nba:0022300904"]


def test_game_family_over_reserved_shot_records_is_refused(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    _res(c, fam="SHOTS", ids=["SHOT:0022300901:1", "SHOT:0022300901:2"])
    with pytest.raises(ExposureRefused):
        _res(c, fam="GAMES", ids=["nba:0022300901"])


# --------------------------------------------------------------------------- ruling: 2nd amendment needs sign-off
def test_second_amendment_needs_reviewer_signoff(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    rid = _res(c, inp="A")["receipt_id"]; c.spend(rid)
    _replay(c, rid, am="am1", code="c2")                            # first amendment: no sign-off needed
    with pytest.raises(ExposureRefused, match="sign-off"):
        _replay(c, rid, am="am2", code="c3")
    with pytest.raises(ExposureRefused, match="sign-off"):         # sign-off naming another amendment
        c.replay(receipt_id=rid, family_id="F1", epoch_id="E-F1", record_ids=IDS, amendment_hash="am2",
                 code_hash="c3", input_hash="A",
                 reviewer_signoff={"reviewer": "rv", "receipt_id": rid, "amendment_hash": "am1"})
    ok = c.replay(receipt_id=rid, family_id="F1", epoch_id="E-F1", record_ids=IDS, amendment_hash="am2",
                  code_hash="c3", input_hash="A",
                  reviewer_signoff={"reviewer": "rv", "receipt_id": rid, "amendment_hash": "am2"})
    assert ok["reviewer_signoff"]["reviewer"] == "rv"


# --------------------------------------------------------------------------- seal / register
def _seal(c, ids, inp="S", epoch="E-SEAL"):
    return c.seal(epoch_id=epoch, record_ids=ids, input_hash=inp, data_hashes={"t": "h"}, description="test")


def _reg(c, fam="CONF", plan="P", code="C", epoch="E-SEAL"):
    return c.register(epoch_id=epoch, family_id=fam, plan_hash=plan, code_hash=code)


SEALED = ["0022400001", "0022400002", "0022400003"]


def test_sealed_games_only_open_to_the_registered_job(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    _seal(c, SEALED)
    with pytest.raises(ExposureRefused, match="not registered"):     # unregistered family
        c.reserve(family_id="CONF", epoch_id="E-SEAL", plan_hash="P", code_hash="C", record_ids=SEALED,
                  input_hash="S")
    _reg(c)
    with pytest.raises(ExposureRefused):                             # another family, other epoch
        c.reserve(family_id="X", epoch_id="E-X", plan_hash="P", code_hash="C", record_ids=SEALED[:1])
    with pytest.raises(ExposureRefused):                             # shot ids of a sealed game
        c.reserve(family_id="X", epoch_id="E-X", plan_hash="P", code_hash="C", record_ids=["SHOT:0022400002:9"])
    with pytest.raises(ExposureRefused, match="whole"):              # subset of the seal
        c.reserve(family_id="CONF", epoch_id="E-SEAL", plan_hash="P", code_hash="C", record_ids=SEALED[:2],
                  input_hash="S")
    with pytest.raises(ExposureRefused, match="sealed data"):        # different data
        c.reserve(family_id="CONF", epoch_id="E-SEAL", plan_hash="P", code_hash="C", record_ids=SEALED,
                  input_hash="other")
    with pytest.raises(ExposureRefused, match="not registered"):     # registered family, edited plan
        c.reserve(family_id="CONF", epoch_id="E-SEAL", plan_hash="P2", code_hash="C", record_ids=SEALED,
                  input_hash="S")
    r = c.reserve(family_id="CONF", epoch_id="E-SEAL", plan_hash="P", code_hash="C", record_ids=SEALED,
                  input_hash="S")
    assert not r["retry"]
    with pytest.raises(ExposureRefused, match="registration closed"):
        _reg(c, plan="P-late")


def test_seal_refuses_exposed_games_and_second_family(tmp_path):
    c = Custodian(tmp_path / "l.jsonl")
    _res(c, fam="OLD", ids=["0022400001"])
    with pytest.raises(ExposureRefused):
        _seal(c, SEALED)
    c2 = Custodian(tmp_path / "l2.jsonl")
    assert not _seal(c2, SEALED)["retry"] and _seal(c2, SEALED)["retry"]
    with pytest.raises(ExposureRefused):
        _seal(c2, SEALED, inp="different")
    _reg(c2)
    assert _reg(c2)["retry"]
    with pytest.raises(ExposureRefused, match="different registered family"):
        _reg(c2, fam="OTHER")
    with pytest.raises(ExposureRefused, match="no seal"):
        _reg(c2, epoch="E-NONE")


@real
def test_gp_second_amendment_runs_only_with_reviewer_signoff(tmp_path):
    """The committed ledger already holds the amendment-1 replay, so amendment-2 needs sign-off (D15)."""
    gp = _gp(); out = _evidence_copy(tmp_path)
    gp.amend(DATA, out, "test amendment 2")
    am2 = json.loads((out / "claim_plan_GP.amendment-2.json").read_text())
    before = (out / "custodian_ledger.jsonl").read_bytes()
    with pytest.raises(ExposureRefused, match="sign-off"):
        gp.final(DATA, out)
    assert (out / "custodian_ledger.jsonl").read_bytes() == before
    (out / "claim_plan_GP.amendment-2.signoff.json").write_text(json.dumps(
        {"reviewer": "pytest-reviewer", "receipt_id": "3e238d2d-030e-45b4-aae7-db0787ecb873",
         "amendment_hash": am2["canonical_amendment_hash"]}))
    gp.final(DATA, out)
    r = json.loads((out / "game_prediction_final.replay-GP-2023-24-C1-vs-B1-AMEND-2.json").read_text())
    assert r["replay"]["reviewer_signoff"]["reviewer"] == "pytest-reviewer"
    orig = json.loads((ROOT / "evidence/game_prediction_final.json").read_text())
    assert r["decisions"] == orig["decisions"]


def test_write_once_never_overwrites(tmp_path):
    gp = _gp()
    p = tmp_path / "r.json"
    assert gp._write_once(p, "first\n") == p
    assert gp._write_once(p, "second\n").name == "r.rerun-1.json"
    assert gp._write_once(p, "third\n").name == "r.rerun-2.json"
    assert p.read_text() == "first\n"


@real
def test_gp_replay_rerun_keeps_first_result_file(tmp_path):
    gp = _gp(); out = _evidence_copy(tmp_path)
    gp.amend(DATA, out, "test amendment 2")
    am2 = json.loads((out / "claim_plan_GP.amendment-2.json").read_text())
    (out / "claim_plan_GP.amendment-2.signoff.json").write_text(json.dumps(
        {"reviewer": "pytest-reviewer", "receipt_id": "3e238d2d-030e-45b4-aae7-db0787ecb873",
         "amendment_hash": am2["canonical_amendment_hash"]}))
    name = "game_prediction_final.replay-GP-2023-24-C1-vs-B1-AMEND-2"
    gp.final(DATA, out)
    first = (out / f"{name}.json").read_bytes()
    gp.final(DATA, out)                                   # rerun: replay retry
    assert (out / f"{name}.json").read_bytes() == first   # first result untouched (timestamp included)
    rerun = json.loads((out / f"{name}.rerun-1.json").read_text())
    assert rerun["replay"]["retry"] is True and rerun["decisions"] == json.loads(first)["decisions"]
    committed = ROOT / "evidence/game_prediction_final.replay-GP-2023-24-C1-vs-B1-AMEND-1.json"
    assert (out / committed.name).read_bytes() == committed.read_bytes()
