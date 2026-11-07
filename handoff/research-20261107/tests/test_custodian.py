import multiprocessing as mp

import pytest

from heatcheck.custodian import Custodian, ExposureRefused

IDS = ["0022300901", "0022300902", "0022300903"]


def test_reserve_spend_and_identical_retry(tmp_path):
    c = Custodian(tmp_path / "ledger.jsonl")
    r1 = c.reserve(family_id="F1", epoch_id="E1", plan_hash="p", code_hash="c", record_ids=IDS)
    assert not r1["retry"]
    r2 = c.reserve(family_id="F1", epoch_id="E1", plan_hash="p", code_hash="c", record_ids=list(reversed(IDS)))
    assert r2["retry"] and r2["receipt_id"] == r1["receipt_id"]
    c.spend(r1["receipt_id"]); assert c.is_spent(r1["receipt_id"])


def test_new_family_id_cannot_reopen_exposed_records(tmp_path):
    c = Custodian(tmp_path / "ledger.jsonl")
    c.reserve(family_id="F1", epoch_id="E1", plan_hash="p", code_hash="c", record_ids=IDS)
    with pytest.raises(ExposureRefused):
        c.reserve(family_id="F2-renamed", epoch_id="E2", plan_hash="p2", code_hash="c", record_ids=IDS[1:])


def test_changed_code_is_not_a_retry(tmp_path):
    c = Custodian(tmp_path / "ledger.jsonl")
    c.reserve(family_id="F1", epoch_id="E1", plan_hash="p", code_hash="c", record_ids=IDS)
    with pytest.raises(ExposureRefused):
        c.reserve(family_id="F1", epoch_id="E1", plan_hash="p", code_hash="c-edited", record_ids=IDS)


def test_ledger_persists_across_restart(tmp_path):
    path = tmp_path / "ledger.jsonl"
    Custodian(path).reserve(family_id="F1", epoch_id="E1", plan_hash="p", code_hash="c", record_ids=IDS)
    with pytest.raises(ExposureRefused):
        Custodian(path).reserve(family_id="F9", epoch_id="E9", plan_hash="q", code_hash="d", record_ids=[IDS[0]])


def _race(path, i, q):
    try:
        Custodian(path).reserve(family_id=f"F{i}", epoch_id=f"E{i}", plan_hash="p", code_hash="c", record_ids=IDS)
        q.put("ok")
    except ExposureRefused:
        q.put("refused")


def test_concurrent_reservations_only_one_wins(tmp_path):
    path = tmp_path / "ledger.jsonl"; q = mp.Queue()
    ps = [mp.Process(target=_race, args=(path, i, q)) for i in range(6)]
    [p.start() for p in ps]; [p.join() for p in ps]
    res = sorted(q.get() for _ in ps)
    assert res.count("ok") == 1 and res.count("refused") == 5
