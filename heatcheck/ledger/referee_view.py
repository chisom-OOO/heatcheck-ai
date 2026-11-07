"""Read-only projection of an evidence-ledger entry for display: heatcheck-referee-view/1.

The ledger entry (heatcheck/ledger/evidence.py) is hashed and never changed. This module only
reads an entry that the ledger has already verified and returns a new dict in the shape
documented in docs/REFEREE_VIEW_FORMAT.md. Pure: no files, no network.

Values are copied, not recomputed or rounded. Attack ``status`` is copied as recorded
(EXECUTED / FAILED / UNSUPPORTED): a per-attack PASSED does not exist, because only the
Referee's decision over all attacks says whether the claim survived.
"""

from __future__ import annotations

from typing import Any

VIEW_FORMAT = "heatcheck-referee-view/1"


def _role(identity: dict, *keep: str) -> dict:
    out = {k: identity.get(k) for k in ("role", "display_name", "kind", "model", "reasoning_effort",
                                        *keep) if k in identity}
    if "fallback_reason" in identity:
        out["fallback_reason"] = identity["fallback_reason"]
    return out


def referee_view(entry: dict[str, Any]) -> dict[str, Any]:
    i = entry["identity"]
    plan = i["claim"]["plan"]
    attacks = [{
        "test_id": r["test_id_version"],
        "status": r["status"],
        "statistic": r["statistic"],
        "effect_estimate": r["effect_estimate"],
        "interval": r["interval"],
        "p_value": r["p_value"],
        "method": r["null_method_assumptions"],
        "reason": r["reason"],
        "evidence_hash": r["evidence_hash"],
    } for r in i["attack_results"]]

    ev: list[dict] = []

    def add(label, value, kind):
        ev.append({"label": label, "value": value, "kind": kind})

    add("evidence id", entry["evidence_id"], "hash")
    add("ledger entry hash", entry["entry_hash"], "hash")
    add("recorded at (UTC)", entry["created_at_utc"], "time")
    d = i["data"]
    add("data source (records sha256 or generator)", d.get("source"), "hash")
    add("shot arrays sha256", d.get("arrays_sha256"), "hash")
    add("field-goal attempts", d.get("n_attempts"), "count")
    add("player-games", d.get("n_groups"), "count")
    add("games", d.get("n_games"), "count")
    for r in i["attack_results"]:
        if r["test_id_version"].startswith("A-PERMUTATION-NULL") and r["status"] == "EXECUTED":
            add("effect estimate (bias-corrected, make-rate difference)", r["effect_estimate"], "estimate")
            add("permutation p-value", r["p_value"], "estimate")
    for path, h in sorted(i["code"].items()):
        add(f"code sha256 {path}", h, "hash")
    add("referee rule", i["referee"].get("rule"), "version")

    return {
        "format": VIEW_FORMAT,
        "derived_from": {"evidence_id": entry["evidence_id"], "entry_hash": entry["entry_hash"],
                         "created_at_utc": entry["created_at_utc"]},
        "protocol_version": i["protocol_version"],
        "registry_version": i["registry_version"],
        "channel": i["channel"],
        "data_mode": d.get("data_mode"),
        "claim": {"claim_id": i["claim"]["claim_id"], "version": i["claim"]["version"],
                  "statement": plan.get("statement"), "estimand": plan.get("estimand"),
                  "plan_hash": i["claim"]["canonical_plan_hash"], "revision": None,
                  "params": plan.get("params")},
        "attacks_run": attacks,
        "verdict": {"decision": i["decision"], "reason": i["reason"]},
        "evidence": ev,
        "roles": {"discoverer": _role(i["proposer"]),
                  "challenger": {**_role(i["challenger"]),
                                 "selected_attacks": i["challenger"].get("selected_attacks", [])},
                  "referee": _role(i["referee"], "rule")},
        "limits": i["limits"],
    }
