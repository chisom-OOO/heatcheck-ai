"""Confirmatory lane (scripts/confirmatory.py): decision rules on fixed numbers, and an end-to-end smoke test
of seal -> freeze -> final on a TEMPORARY ledger over a small subset of 2023-24 DEVELOPMENT games.
The real 2024-25 seal is never touched here. Real-data tests are SKIPPED without the dataset: NOT_RUN."""
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from heatcheck import splits as S
from heatcheck import store
from heatcheck.custodian import Custodian, ExposureRefused
from heatcheck.util import canonical_json, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]


def _cf():
    spec = importlib.util.spec_from_file_location("conf_under_test", ROOT / "scripts/confirmatory.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


CF = _cf()


def _plans():
    return {h: {"params": v["params"]} for h, v in CF.HYPOTHESES.items()}


def _ha(mean, lo, hi, p, n=1200):
    return {"status": "EXECUTED", "n_games": n, "mean": mean, "ci95": [lo, hi], "p_one_sided": p}


def _st(p, n=150000, a=5000, b=5000):
    return {"status": "EXECUTED", "n_fga": n, "n_after_makes": a, "n_after_misses": b, "p_one_sided": p}


def test_decision_rules_and_holm():
    d = CF.decide({"CONF-HA": _ha(0.05, 0.03, 0.07, 0.001), "CONF-MOM": _st(0.004), "CONF-HH": _st(0.5)}, _plans())
    assert d["CONF-HA"]["decision"] == "SURVIVED_PROTOCOL"
    assert d["CONF-MOM"]["decision"] == "SURVIVED_PROTOCOL" and d["CONF-MOM"]["p_holm"] == pytest.approx(0.008)
    assert d["CONF-HH"]["decision"] == "INSUFFICIENT_EVIDENCE"


def test_home_rule_floor_ci_and_minimums():
    p = _plans()
    assert CF.decide({"CONF-HA": _ha(0.005, -0.01, 0.009, 0.2), "CONF-MOM": _st(0.5), "CONF-HH": _st(0.5)},
                     p)["CONF-HA"]["decision"] == "NOT_SUPPORTED"
    assert CF.decide({"CONF-HA": _ha(0.008, 0.001, 0.02, 0.001), "CONF-MOM": _st(0.5), "CONF-HH": _st(0.5)},
                     p)["CONF-HA"]["decision"] == "INSUFFICIENT_EVIDENCE"            # mean below floor
    assert CF.decide({"CONF-HA": _ha(0.05, 0.03, 0.07, 0.001, n=900), "CONF-MOM": _st(0.5), "CONF-HH": _st(0.5)},
                     p)["CONF-HA"]["decision"] == "INSUFFICIENT_EVIDENCE"            # too few games


def test_shot_rule_minimums_and_undefined():
    p = _plans()
    d = CF.decide({"CONF-HA": _ha(0.05, 0.03, 0.07, 0.001), "CONF-MOM": _st(0.001, n=90000),
                   "CONF-HH": {"status": "UNDEFINED"}}, p)
    assert d["CONF-MOM"]["decision"] == "INSUFFICIENT_EVIDENCE" and d["CONF-HH"]["decision"] == "INSUFFICIENT_EVIDENCE"


def test_streak_test_matches_kernel_on_synthetic_frame():
    f = pd.DataFrame({"game_id": ["g"] * 8, "person_id": [1.0] * 8, "sequence": range(8),
                      "shot_value": [2] * 8, "made": [1, 1, 0, 1, 1, 1, 0, 0]})
    r = CF.streak_test(f, {"k": 1, "B": 19, "seed": 1})
    assert r["n_after_makes"] == 5 and r["hits_after_makes"] == 3 and r["n_after_misses"] == 2
    assert r["hits_after_misses"] == 1   # positions 3 (made) and 7 (missed) follow a miss
    assert r["T"] == pytest.approx(3 / 5 - 1 / 2) and 0 < r["p_one_sided"] <= 1


# --------------------------------------------------------------------------- end-to-end on a temporary seal
DATA = Path(os.environ.get("HC_DATA", ROOT / "data/run1"))
real = pytest.mark.skipif(not (DATA / "public.sqlite").exists(), reason="NOT_RUN: dataset not built")
SMALL = {"CONF-HA": {"B": 199}, "CONF-MOM": {"B": 19}, "CONF-HH": {"B": 19}}


@pytest.fixture(scope="module")
def small_dev_season(tmp_path_factory):
    """~62 development games spread across fit/tune/calibration, stored like a one-season build."""
    d = tmp_path_factory.mktemp("small_season")
    games = store.read(DATA / "public.sqlite", "games")
    games["tip_utc"] = pd.to_datetime(games.tip_utc, utc=True)
    sp, _ = S.make_splits(games)
    ids = sorted(sp[sp.split != "final"].game_id)[::15]
    lf = {t: store.logical_frame(store.read(DATA / f"{db}.sqlite", t))
          for t, db in [("games", "public"), ("game_labels", "restricted_labels"), ("shot_labels", "restricted_labels")]}
    con = sqlite3.connect(f"file:{DATA / 'public.sqlite'}?mode=ro", uri=True)
    ev = pd.read_sql(f"SELECT * FROM events WHERE game_id IN ({','.join('?' * len(ids))})", con, params=ids)
    con.close()
    store.publish(d / "public.sqlite", {"games": lf["games"][lf["games"].game_id.isin(ids)],
                                        "events": store.logical_frame(ev),
                                        "exclusions": pd.DataFrame({"game_id": pd.Series(dtype=str),
                                                                    "reason": pd.Series(dtype=str)}),
                                        "quarantine": pd.DataFrame({"game_id": [ids[0]],
                                                                    "reason": ["TEST quarantine"]})})
    store.publish(d / "restricted_labels.sqlite",
                  {"game_labels": lf["game_labels"][lf["game_labels"].game_id.isin(ids)],
                   "shot_labels": lf["shot_labels"][lf["shot_labels"].game_id.isin(ids)]}, restricted=True)
    return d, ids


def _seal_small(evidence, data, ids):
    hashes = store.logical_table_hashes(data, store.SEASON_TABLES)
    Custodian(evidence / "custodian_ledger.jsonl").seal(
        epoch_id=CF.EPOCH_ID, record_ids=ids, input_hash=sha256_bytes(canonical_json(hashes)),
        data_hashes=hashes, description="TEST seal over 2023-24 development games")


@real
def test_end_to_end_seal_freeze_final_on_temporary_ledger(tmp_path, small_dev_season):
    data, ids = small_dev_season
    ev = tmp_path / "evidence"; ev.mkdir()
    _seal_small(ev, data, ids)
    CF.freeze(data, ev, overrides=SMALL)
    with pytest.raises(CF.Refused, match="authorised"):
        CF.final(data, ev, "")
    CF.final(data, ev, "pytest")
    r = json.loads((ev / CF.SUBDIR / "final_result.json").read_text())
    assert set(r["decisions"]) == {"CONF-HA", "CONF-MOM", "CONF-HH"}
    assert r["results"]["CONF-HA"]["n_games"] > 0 and r["results"]["CONF-HH"]["n_fga"] > 0
    assert all(v["decision"] == "INSUFFICIENT_EVIDENCE" for v in r["decisions"].values())  # below sample minimums
    assert [e["type"] for e in r["ledger_history_of_receipt"]] == ["reserve", "spend"]
    assert r["results"]["_quarantined_games_excluded"] == [ids[0]]                    # D19
    assert r["results"]["CONF-HA"]["n_games"] + r["results"]["CONF-HA"]["neutral_excluded"] == len(ids) - 1
    first = r["exposure_receipt_id"]
    CF.final(data, ev, "pytest")                                         # identical retry: same receipt
    assert json.loads((ev / CF.SUBDIR / "final_result.json").read_text())["exposure_receipt_id"] == first


@real
def test_final_refuses_edited_plan_and_changed_data(tmp_path, small_dev_season):
    data, ids = small_dev_season
    ev = tmp_path / "evidence"; ev.mkdir()
    _seal_small(ev, data, ids)
    CF.freeze(data, ev, overrides=SMALL)
    with pytest.raises(CF.Refused):
        CF.freeze(data, ev, overrides=SMALL)                             # never overwrites plans
    plan_p = ev / CF.SUBDIR / "CONF-HA.plan.json"
    original = plan_p.read_text()
    plan = json.loads(original); plan["params"]["practical_floor"] = 0.0
    plan_p.write_text(json.dumps(plan))
    with pytest.raises(CF.Refused, match="edited after freeze"):
        CF.final(data, ev, "pytest")
    plan_p.write_text(original)
    tampered = tmp_path / "tampered"; tampered.mkdir()
    (tampered / "public.sqlite").symlink_to(data / "public.sqlite")
    (tampered / "restricted_labels.sqlite").write_bytes((data / "restricted_labels.sqlite").read_bytes())
    con = sqlite3.connect(tampered / "restricted_labels.sqlite")
    con.execute("UPDATE game_labels SET home_win = 1 - home_win WHERE rowid <= 5"); con.commit(); con.close()
    ledger = (ev / "custodian_ledger.jsonl").read_bytes()
    with pytest.raises(CF.Refused, match="sealed data"):
        CF.final(tampered, ev, "pytest")
    assert (ev / "custodian_ledger.jsonl").read_bytes() == ledger


@real
def test_registration_closed_once_family_frozen(tmp_path, small_dev_season):
    data, ids = small_dev_season
    ev = tmp_path / "evidence"; ev.mkdir()
    _seal_small(ev, data, ids)
    CF.freeze(data, ev, overrides=SMALL)
    with pytest.raises(ExposureRefused, match="different registered family"):
        Custodian(ev / "custodian_ledger.jsonl").register(epoch_id=CF.EPOCH_ID, family_id=CF.FAMILY_ID,
                                                         plan_hash="another-plan", code_hash=CF.code_hash())
