"""Independent pre-shot invariance harness (R-001 A4-A6), reviewer-owned.

Stronger than A4 as written: flipping shot k must leave the rows of shot k AND of every
earlier shot byte-identical, and the builder must not depend on input list order.
"""

from __future__ import annotations

import copy
import json
import os
import random

import pytest

from heatcheck.contracts.bundle import load_bundle
from heatcheck.contracts.records import validate_record
from tests.review.review_support import (
    ENV_FEATURE_BUILDER,
    ENV_RESEARCH_BUNDLE,
    ENV_RESEARCH_SYN_BUNDLE,
    downstream_changes,
    env_path,
    invariance_violations,
    leaky_builder,
    load_callable,
    no_network,  # noqa: F401  (fixture)
    of_type,
    reference_builder,
    reference_records,
    rows_by_shot,
    synthetic_game,
)


def ref_events():
    return of_type(reference_records(), "EVENT")


# --------------------------------------------------------------------------- harness self-tests


@pytest.mark.parametrize("events", [synthetic_game(), ref_events()], ids=["syn_ot", "ref"])
def test_reviewer_builder_is_invariant(no_network, events):  # noqa: F811
    assert invariance_violations(reference_builder, events) == []
    for row in reference_builder(events):
        validate_record(row)


@pytest.mark.parametrize("events", [synthetic_game(), ref_events()], ids=["syn_ot", "ref"])
def test_negative_control_leaky_builder_is_caught(no_network, events):  # noqa: F811
    assert invariance_violations(leaky_builder, events), "harness failed to detect a leak"


def test_harness_is_sensitive_downstream(no_network):  # noqa: F811
    assert downstream_changes(reference_builder, synthetic_game()) > 0


def test_reviewer_builder_free_throw_and_overtime_values():
    rows = {r["body"]["target_id"].rsplit(":", 1)[-1]: r["body"]["features"]
            for r in reference_builder(synthetic_game())}
    # e8 is FT 2 of 2 by AWAY after FT 1 made: margin includes FT 1 (prior event), not FT 2.
    assert rows["e8"]["pre_shot_margin_shooting_team"]["value"] == -1
    assert rows["e8"]["player_prior_makes_in_game"]["value"] == 1  # e3 miss, e7 make
    # e19 is the HOME OT shot after e18's FT tied the game 8-8.
    assert rows["e19"]["period"]["value"] == 5
    assert rows["e19"]["pre_shot_margin_shooting_team"]["value"] == 0


# --------------------------------------------------------------------------- candidate builder


def candidate_builder():
    spec = os.environ.get(ENV_FEATURE_BUILDER)
    if not spec:
        pytest.skip(f"NOT_RUN: set {ENV_FEATURE_BUILDER}=module:function (Research builder)")
    return load_callable(spec)


def candidate_event_sets():
    sets = {"reviewer_syn_ot": synthetic_game(), "max_reference": ref_events()}
    for name, env in (("research_real", ENV_RESEARCH_BUNDLE),
                      ("research_syn", ENV_RESEARCH_SYN_BUNDLE)):
        path = env_path(env)
        if path is not None:
            sets[name] = of_type(load_bundle(path)[1], "EVENT")
    return sets


def test_candidate_builder_invariance(no_network):  # noqa: F811
    build = candidate_builder()
    failures = {}
    for name, events in candidate_event_sets().items():
        v = invariance_violations(build, events)
        if v:
            failures[name] = v[:10]
    assert not failures, f"EXPECTED no changed pre-shot rows; ACTUAL {failures}"
    if env_path(ENV_RESEARCH_BUNDLE) is None:
        pytest.skip(f"real-game invariance NOT_RUN: set {ENV_RESEARCH_BUNDLE} (synthetic sets PASSED)")


def test_candidate_builder_downstream_sensitive(no_network):  # noqa: F811
    build = candidate_builder()
    assert downstream_changes(build, synthetic_game()) > 0, "flip never propagates downstream"


def test_candidate_builder_ignores_input_order(no_network):  # noqa: F811
    build = candidate_builder()
    events = synthetic_game()
    shuffled = copy.deepcopy(events)
    random.Random(20261107).shuffle(shuffled)
    assert rows_by_shot(build(copy.deepcopy(events)), events) == \
        rows_by_shot(build(shuffled), events), "rows depend on input list order, not sequence"


def _decision_content(rows: dict[str, bytes]) -> dict[str, tuple]:
    """What a model can see: feature values, cutoff and declared max input. Provenance
    hashes are excluded on purpose: they must change when an input EVENT's bytes change."""
    out = {}
    for k, raw in rows.items():
        b = json.loads(raw)["body"]
        out[k] = (json.dumps(b["features"], sort_keys=True), json.dumps(b["cutoff"], sort_keys=True),
                  b["max_input_sequence"])
    return out


def test_candidate_builder_ignores_assist_attribution(no_network):  # noqa: F811
    """Changing post-outcome assist attribution must not change any feature value.
    (Revised 2026-11-07 after Max's diagnosis: the first version compared whole rows, and
    source_record_hashes legitimately change when an input EVENT's assist field changes.)"""
    build = candidate_builder()
    events = synthetic_game()
    base = rows_by_shot(build(copy.deepcopy(events)), events)
    mutated = copy.deepcopy(events)
    for e in mutated:
        if e["body"]["shot"] and e["body"]["shot"]["kind"] == "FIELD_GOAL" \
                and e["body"]["shot"]["made"]:
            e["body"]["shot"]["assisted_post_outcome"] = not bool(
                e["body"]["shot"]["assisted_post_outcome"])
    after = rows_by_shot(build(mutated), mutated)
    assert _decision_content(base) == _decision_content(after), \
        "assist attribution changed a pre-shot feature value"


def test_reviewer_builder_passes_assist_check():
    """Positive control for the revised assist test (the old version failed this)."""
    events = synthetic_game()
    mutated = copy.deepcopy(events)
    for e in mutated:
        if e["body"]["shot"] and e["body"]["shot"]["made"] and e["body"]["shot"]["kind"] == "FIELD_GOAL":
            e["body"]["shot"]["assisted_post_outcome"] = not bool(e["body"]["shot"]["assisted_post_outcome"])
    a = rows_by_shot(reference_builder(copy.deepcopy(events)), events)
    b = rows_by_shot(reference_builder(mutated), mutated)
    assert _decision_content(a) == _decision_content(b)


def test_candidate_builder_emits_valid_records(no_network):  # noqa: F811
    build = candidate_builder()
    events = synthetic_game()
    rows = build(copy.deepcopy(events))
    assert rows, "builder produced no rows"
    for r in rows:
        validate_record(r)
    got = set(rows_by_shot(rows, events))
    fgs = {e["body"]["provider_event_id"] for e in events
           if e["body"]["action"] == "SHOT" and e["body"]["shot"]["kind"] == "FIELD_GOAL"}
    assert fgs <= got, f"field goals without a row: {sorted(fgs - got)}"


def test_candidate_builder_covers_free_throws(no_network):  # noqa: F811
    """R-001 deliverable 1: one PRE_SHOT_MAKE row per shot attempt. Free throws are shot
    attempts in heatcheck-records/1 (action SHOT, kind FREE_THROW)."""
    build = candidate_builder()
    events = synthetic_game()
    got = set(rows_by_shot(build(copy.deepcopy(events)), events))
    fts = {e["body"]["provider_event_id"] for e in events
           if e["body"]["action"] == "SHOT" and e["body"]["shot"]["kind"] == "FREE_THROW"}
    assert fts <= got, (f"EXPECTED a row per free throw (R-001 deliverable 1); ACTUAL none for "
                        f"{sorted(fts - got)}. Needs a row or a Max-approved exclusion policy.")
