"""Free-dialogue layer: Heater (Discoverer display name), LLM Challenger, Ref phrasing guard,
timeouts and fallbacks, the /api/dialogue endpoint and the usage log.

No network: every provider reply comes from FakeTransport. Expectations were written from the
user's specification (2026-11-07) before the first run:
* NONE -> no test runs, no ledger write, Ref says no registered test exists.
* an unregistered claim/attack id from the LLM is never run (fallback to stand-in).
* any Ref number or verdict word not in the evidence record -> template.
* provider failure or > timeout -> deterministic text; all four fields always returned.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from decimal import Decimal
from threading import Thread

import pytest

pytest.importorskip("pandas")

from heatcheck.agents.dialogue import (  # noqa: E402
    HEATER_FALLBACK,
    HEATER_TAKE_FALLBACK,
    NO_TEST_REF,
    Dialogue,
    LLMChallenger,
    allowed_numbers,
    keyword_map,
    parse_mapping,
    ref_facts,
    ref_guard,
    ref_template,
    take_mentions_ref,
)
from heatcheck.agents.llm import LLMUnavailable, MetaChat, usage_summary  # noqa: E402
from heatcheck.agents.views import shot_view_from_league  # noqa: E402
from heatcheck.api.dialogue_server import serve  # noqa: E402
from heatcheck.contracts.research_bridge import research_module  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402

FAKE_KEY = "test-key-NOT-A-SECRET-0123456789"
USAGE = {"prompt_tokens": 50, "completion_tokens": 40,
         "completion_tokens_details": {"reasoning_tokens": 20}, "prompt_tokens_details": {"cached_tokens": 0}}


def chat_json(content, finish="stop"):
    return [json.dumps({"id": "chatcmpl-fake", "choices": [{"finish_reason": finish, "message": {
        "content": content, "role": "assistant"}}], "usage": USAGE}).encode()]


def chat_sse(text):
    lines = [f"data: {json.dumps({'id': 'x', 'choices': [{'delta': {'content': w + ' '}}]})}\n".encode()
             for w in text.split()]
    lines.append(f"data: {json.dumps({'id': 'x', 'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n".encode())
    lines.append(f"data: {json.dumps({'id': 'x', 'choices': [], 'usage': USAGE})}\n".encode())
    lines.append(b"data: [DONE]\n")
    return lines


class FakeTransport:
    """Routes by request shape: mapping / challenger (json_schema name), heater (stream), ref."""

    def __init__(self, mapping='{"claim_id": "HH-K3"}', challenger=None, heater="WHAT A NIGHT, folks!",
                 ref=None, delay=0.0, fail_code=None):
        self.mapping, self.challenger, self.heater, self.ref = mapping, challenger, heater, ref
        self.delay, self.fail_code = delay, fail_code
        self.calls: list[dict] = []
        self.seen_auth: list[str] = []

    def post(self, url, headers, body, timeout):
        b = json.loads(body)
        self.calls.append(b)
        self.seen_auth.append(headers["Authorization"])
        time.sleep(self.delay)
        if self.fail_code:
            return self.fail_code, iter([b'{"error":{"message":"boom"}}'])
        if b"uniqueItems" in body:  # the real API's behaviour, observed live 2026-11-07T17:27Z
            return 400, iter([b'{"error":{"message":"JSON schema keyword `uniqueItems` is not supported"}}'])
        name = ((b.get("response_format") or {}).get("json_schema") or {}).get("name")
        if name == "claim_mapping":
            return 200, iter(chat_json(self.mapping))
        if name == "attack_selection":
            sel = self.challenger if self.challenger is not None else json.dumps(
                {"attacks": ["A-SPLIT-HALF-REPLICATION"]})
            return 200, iter(chat_json(sel))
        if b.get("stream"):
            return 200, iter(chat_sse(self.heater))
        return 200, iter(chat_json(self.ref or "unused"))


@pytest.fixture(scope="module")
def view():
    lg, _truth = research_module("simulate").generate(101, "A", 0.0)
    return shot_view_from_league(lg, "research simulate.generate family=A seed=101")


def llm(tmp_path, transport, timeout=8.0):
    return MetaChat(transport=transport, api_key=FAKE_KEY, usage_log=tmp_path / "usage.jsonl",
                    timeout_s=timeout)


_DET: dict = {}


def deterministic_entry(view, tmp_path):
    """One deterministic HH-K3 turn per module (the permutation test is the slow part)."""
    if "v" not in _DET:
        d = Dialogue(view, EvidenceLedger(tmp_path / "det.jsonl"), None)
        out = d.turn("is the hot hand real? three in a row")
        _DET["v"] = (out, d.ledger.get(out["evidence_record_id"]))
    return _DET["v"]


# --------------------------------------------------------------------------- Ref guard


def test_guard_rejects_invented_number(view, tmp_path):
    _, entry = deterministic_entry(view, tmp_path)
    facts = ref_facts(entry)
    decision = facts["decision"]
    phrase = {"SURVIVED_PROTOCOL": "survived", "NOT_SUPPORTED": "not supported",
              "INSUFFICIENT_EVIDENCE": "insufficient evidence", "DATA_INVALID": "data invalid",
              "BLOCKED": "blocked"}[decision]
    honest = f"The claim is {phrase}. It used {facts['data']['n_attempts']} attempts."
    assert ref_guard(honest, facts) == []
    invented = f"The claim is {phrase}. Shooters improved by 12.7 percent over 4321 attempts."
    problems = ref_guard(invented, facts)
    assert any("12.7" in p for p in problems) and any("4321" in p for p in problems), problems
    assert ("+", Decimal(17)) not in allowed_numbers(facts)
    assert any("17" in p for p in ref_guard(f"The claim is {phrase} in seventeen games.", facts))


def test_guard_rejects_sign_flip_spelled_and_percent_numbers(view, tmp_path):
    _, entry = deterministic_entry(view, tmp_path)
    facts = ref_facts(entry)
    perm = next(a for a in facts["attacks"] if a["test"].startswith("A-PERMUTATION"))
    p = perm["p_value"]
    assert ref_guard(f"Verdict: {facts['decision']}. p={p}.", facts) == []
    assert ref_guard(f"Verdict: {facts['decision']}. p=-{p}.", facts)          # sign flip
    assert ("+", Decimal(90)) not in allowed_numbers(facts)
    assert any("90" in p for p in ref_guard(f"Verdict: {facts['decision']}. Ninety teams.", facts))
    assert ref_guard(f"Verdict: {facts['decision']}. That is 73% of shots.", facts)


def test_guard_rejects_wrong_or_overclaimed_verdict(view, tmp_path):
    _, entry = deterministic_entry(view, tmp_path)
    facts = ref_facts(entry)
    d = facts["decision"]
    wrong = "SURVIVED_PROTOCOL" if d != "SURVIVED_PROTOCOL" else "NOT_SUPPORTED"
    assert any(wrong in p for p in ref_guard(f"{d}. Also {wrong}.", facts))
    assert any("proven" in p for p in ref_guard(f"{d}. The hot hand is proven.", facts))
    assert any("myth" in p for p in ref_guard(f"{d}. The hot hand is a myth.", facts))
    assert any("not stated" in p for p in ref_guard("Interesting result tonight.", facts))


@pytest.mark.parametrize("decision", ["SURVIVED_PROTOCOL", "NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE",
                                      "DATA_INVALID", "BLOCKED"])
def test_template_always_passes_guard(view, tmp_path, decision):
    _, entry = deterministic_entry(view, tmp_path)
    facts = {**ref_facts(entry), "decision": decision}
    assert ref_guard(ref_template(facts), facts) == []


def test_ref_is_deterministic_and_never_calls_the_model(view, tmp_path):
    """The Ref is a template built from the evidence entry. Even when the model would return
    an invented number for a Ref call, no Ref call is made and the template is shown."""
    t = FakeTransport(ref="NOT_SUPPORTED and insufficient evidence aside, shooters hit 61.3% when hot.")
    ledger = EvidenceLedger(tmp_path / "l.jsonl")
    out = Dialogue(view, ledger, llm(tmp_path, t)).turn("hot hand, 3 in a row?")
    facts = ref_facts(ledger.get(out["evidence_record_id"]))
    assert out["ref_text"] == ref_template(facts) and out["sources"]["ref"] == "TEMPLATE"
    assert "61.3" not in out["ref_text"]
    assert ref_guard(out["ref_text"], facts) == []   # the template passes the guard itself
    kinds = [((c.get("response_format") or {}).get("json_schema") or {}).get("name") or
             ("heater" if c.get("stream") else "ref") for c in t.calls]
    assert kinds == ["claim_mapping", "heater"]


def test_heater_with_invented_number_falls_back_to_fixed_line(view, tmp_path):
    t = FakeTransport(heater="SHOOTERS HIT 61.3% WHEN HOT, FOLKS!")
    out = Dialogue(view, EvidenceLedger(tmp_path / "l.jsonl"), llm(tmp_path, t)).turn("hot hand three straight?")
    assert out["sources"]["heater"].startswith("TEMPLATE (guard rejected numbers")
    assert out["heater_text"] == HEATER_TAKE_FALLBACK   # verdict-blind: spoken before the Ref
    assert out["heater_reaction"] == HEATER_FALLBACK[out["verdict"]]  # after the stamp


def test_ref_template_shows_display_title_and_reason(view, tmp_path):
    _, entry = deterministic_entry(view, tmp_path)
    text = ref_template(ref_facts(entry))
    assert "Hot hand: three makes in a row (HH-K3)" in text and "Why: " in text


# --------------------------------------------------------------------------- mapping / NONE


def test_none_runs_no_test_and_ref_says_so(view, tmp_path):
    t = FakeTransport(mapping='{"claim_id": "NONE"}', heater="Hot take, just my opinion!")
    ledger = EvidenceLedger(tmp_path / "l.jsonl")
    out = Dialogue(view, ledger, llm(tmp_path, t)).turn("Who has the best sneakers?")
    assert out["claim_id"] == "NONE" and out["verdict"] is None and out["evidence_record_id"] is None
    assert out["ref_text"].startswith("No registered test exists")
    assert out["heater_text"] == "Hot take, just my opinion!"
    assert ledger.all() == []
    assert not any((c.get("response_format") or {}).get("json_schema", {}).get("name") == "attack_selection"
                   for c in t.calls)


@pytest.mark.parametrize("bad", ['{"claim_id": "HH-K9"}', '{"claim_id": "HH-K3", "x": 1}', "not json",
                                 '{"claim_id": "run_my_custom_test"}',
                                 '{"claim_id": "NONE", "claim_id": "HH-K3"}',   # duplicate key (RV-AL6)
                                 '{"claim_id": ["HH-K3"]}', '{"claim_id": "hh-k3"}', '{"claim_id": "HH-K3 "}'])
def test_unregistered_mapping_is_never_run(view, tmp_path, bad):
    t = FakeTransport(mapping=bad)
    ledger = EvidenceLedger(tmp_path / "l.jsonl")
    out = Dialogue(view, ledger, llm(tmp_path, t)).turn("Do left-handers shoot better on Tuesdays?")
    assert out["sources"]["mapping"].startswith("KEYWORD_STANDIN (fallback")
    assert out["claim_id"] == "NONE" and ledger.all() == []          # keyword stand-in: NONE
    with pytest.raises(ValueError):
        parse_mapping(bad)


def test_keyword_standin_mapping():
    assert keyword_map("Is the hot hand real after three straight makes?") == "HH-K3"
    assert keyword_map("two in a row, does he stay hot?") == "HH-K2"
    assert keyword_map("Do back-to-backs hurt teams?") == "GP-REST"
    assert keyword_map("Does a free throw streak continue?") == "NONE"   # FT out of scope
    assert keyword_map("best pizza in Boston") == "NONE"


# --------------------------------------------------------------------------- Challenger


def test_llm_challenger_not_called_when_nothing_is_addable(view, tmp_path):
    """Under heatcheck-registry/1 every applicable attack is required, so the model Challenger
    has nothing it may add and is not called (no latency, no spend)."""
    from heatcheck.agents.registry import CLAIMS
    from heatcheck.agents.roles import required_attacks
    t = FakeTransport()
    ch = LLMChallenger(llm(tmp_path, t))
    assert ch.select(CLAIMS["HH-K3"], view) == required_attacks(CLAIMS["HH-K3"], view)
    assert t.calls == [] and "LLM not called" in ch.note


@pytest.mark.parametrize("reply, ok", [
    ('{"attacks": ["A-EXTRA"]}', True),
    ('{"attacks": []}', True),
    ('{"attacks": ["A-EXTRA"], "attacks": []}', False),          # duplicate key
    ('{"attacks": ["A-MADE-UP"]}', False),                       # unregistered
    ('{"attacks": ["A-EXTRA", "A-EXTRA"]}', False),              # duplicate id
    ('{"attacks": "A-EXTRA"}', False),                           # wrong type
    ('{"attacks": [], "drop": ["A-PERMUTATION-NULL"]}', False),  # unknown field
])
def test_llm_challenger_can_only_add_and_parses_strictly(view, tmp_path, monkeypatch, reply, ok):
    """Simulate a registry with one addable attack ("A-EXTRA"). The model can add it; it can
    never remove a required attack; malformed output falls back to the required set."""
    import heatcheck.agents.dialogue as dlg
    import heatcheck.agents.roles as roles
    from heatcheck.agents.registry import ATTACKS, CLAIMS
    from heatcheck.agents.roles import required_attacks
    monkeypatch.setitem(roles.ATTACKS, "A-EXTRA", ATTACKS["A-SPLIT-HALF-REPLICATION"])
    monkeypatch.setattr(dlg, "addable_attacks", lambda claim, view: ["A-EXTRA"])
    required = required_attacks(CLAIMS["HH-K3"], view)
    ch = LLMChallenger(llm(tmp_path, FakeTransport(challenger=reply)))
    sel = ch.select(CLAIMS["HH-K3"], view)
    assert set(required) <= set(sel)
    if ok:
        assert ch.identity["kind"] == "LLM" and set(sel) - set(required) <= {"A-EXTRA"}
    else:
        assert sel == required and ch.identity["kind"] == "DETERMINISTIC_STANDIN"
        assert ch.fallback_reason


def test_displayed_claim_and_verdict_are_what_ran(view, tmp_path):
    ledger = EvidenceLedger(tmp_path / "l.jsonl")
    out = Dialogue(view, ledger, llm(tmp_path, FakeTransport())).turn("hot hand three straight?")
    e = ledger.get(out["evidence_record_id"])
    assert out["claim_id"] == e["identity"]["claim"]["claim_id"] == "HH-K3"
    assert out["verdict"] == e["identity"]["decision"]


@pytest.mark.parametrize("text", ["p was 6.1e-2.", "n was １４.", "Half of the shots went in.",
                                  "Players get 3 times hotter.", "There is a 6.1% chance.",
                                  "Fourteen of them went in."])
def test_guard_refuses_number_smuggling_forms(view, tmp_path, text):
    _, entry = deterministic_entry(view, tmp_path)
    assert ref_guard(text, ref_facts(entry), require_verdict=False)


# --------------------------------------------------------------------------- failures / timeout


def test_timeout_falls_back_within_deadline(view, tmp_path):
    t = FakeTransport(delay=1.0)
    out = Dialogue(view, EvidenceLedger(tmp_path / "l.jsonl"), llm(tmp_path, t, timeout=0.3)) \
        .turn("hot hand, three in a row?")
    assert set(out) >= {"heater_text", "ref_text", "evidence_record_id", "verdict"}
    assert out["evidence_record_id"] and out["verdict"]
    for k in ("mapping", "heater"):
        assert "fallback" in out["sources"][k], out["sources"]
    assert out["sources"]["ref"] == "TEMPLATE"
    assert "LLM not called" in out["sources"]["challenger"]
    log = [json.loads(x) for x in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert [r["status"] for r in log].count("TIMEOUT") == 2
    # Each provider wait ends at its 0.3 s deadline, not at the 1 s reply. (The turn's total also
    # includes the permutation test on this league, so it is not bounded here.)
    assert all(r["latency_ms"] < 600 for r in log), [r["latency_ms"] for r in log]


def test_http_error_and_missing_key_fall_back(view, tmp_path, monkeypatch):
    out = Dialogue(view, EvidenceLedger(tmp_path / "a.jsonl"), llm(tmp_path, FakeTransport(fail_code=500))) \
        .turn("hot hand three straight")
    assert out["verdict"] and "HTTP_500" in out["sources"]["heater"]
    monkeypatch.delenv("META_API_KEY", raising=False)
    nokey = MetaChat(transport=FakeTransport(), usage_log=tmp_path / "u2.jsonl")
    with pytest.raises(LLMUnavailable, match="META_API_KEY not set"):
        nokey.complete("heater", [{"role": "user", "content": "hi"}])


def test_empty_or_truncated_reply_is_a_failure(tmp_path):
    class T(FakeTransport):
        def post(self, url, headers, body, timeout):
            return 200, iter(chat_json(None, finish="length"))
    with pytest.raises(LLMUnavailable, match="EMPTY_TEXT"):
        llm(tmp_path, T()).complete("ref", [{"role": "user", "content": "x"}])


def test_contributor_models_refused():
    with pytest.raises(ValueError, match="contributor"):
        MetaChat(model="muse-spark-1.3-contributor")


# --------------------------------------------------------------------------- usage log / key


def test_usage_logged_per_call_without_key_or_prompt(view, tmp_path):
    t = FakeTransport()
    Dialogue(view, EvidenceLedger(tmp_path / "l.jsonl"), llm(tmp_path, t)).turn("secret question about hot hand streak")
    raw = (tmp_path / "usage.jsonl").read_text()
    rows = [json.loads(x) for x in raw.splitlines()]
    assert sorted(r["role"] for r in rows) == ["discoverer_map", "heater"]   # Ref: no model
    assert all(r["prompt_tokens"] == 50 and r["completion_tokens"] == 40 and r["est_cost_usd"] > 0 for r in rows)
    assert FAKE_KEY not in raw and "secret question" not in raw
    s = usage_summary(tmp_path / "usage.jsonl")
    assert s["calls"] == 2 and s["tokens"]["prompt"] == 100
    assert all(a == f"Bearer {FAKE_KEY}" for a in t.seen_auth)
    body = json.dumps(t.calls)
    assert FAKE_KEY not in body and all(c["reasoning_effort"] == "minimal" for c in t.calls)
    assert all(c["model"] == "muse-spark-1.3" for c in t.calls)


# --------------------------------------------------------------------------- endpoint


def test_endpoint_returns_four_fields_and_rejects_bad_requests(view, tmp_path):
    srv = serve(Dialogue(view, EvidenceLedger(tmp_path / "l.jsonl"), llm(tmp_path, FakeTransport())), port=0)
    Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/dialogue"
    try:
        req = urllib.request.Request(url, data=json.dumps({"question": "hot hand, three straight?"}).encode(),
                                     headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8765"})
        with urllib.request.urlopen(req, timeout=60) as r:   # the turn runs permutation tests
            out = json.loads(r.read())
            assert r.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
        assert {"heater_text", "ref_text", "evidence_record_id", "verdict", "claim_id",
                "claim_title", "lane", "evidence_source", "sources"} <= set(out)
        assert FAKE_KEY not in json.dumps(out)
        for bad in (b"{}", b'{"question": ""}', b'{"question": 5}', b"nope",
                    json.dumps({"question": "x" * 501}).encode(), b'{"question":"a","extra":1}'):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(url, data=bad), timeout=10)
            assert e.value.code == 400
    finally:
        srv.shutdown()


def test_no_test_template_lists_registered_claims():
    assert "HH-K3" in NO_TEST_REF.format(ids="HH-K3, HH-K2, GP-REST")


def test_console_page_served_and_other_paths_404():
    import threading
    import urllib.error
    import urllib.request

    from heatcheck.api.dialogue_server import serve
    srv = serve(object(), port=0)  # GET never calls the dialogue
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as r:
            body = r.read().decode()
            assert r.status == 200 and r.headers["Content-Type"].startswith("text/html")
            assert "connect-src 'self'" in r.headers["Content-Security-Policy"]
        assert "HeatCheck dialogue console" in body and "/api/dialogue" in body
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/../evidence.jsonl")
        assert e.value.code == 404
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------- Heater speaks before the Ref

def test_heater_take_is_written_without_the_verdict(view, tmp_path):
    t = FakeTransport(heater="HOT HAND IS REAL, I can FEEL it!")
    out = Dialogue(view, EvidenceLedger(tmp_path / "l.jsonl"), llm(tmp_path, t)).turn("hot hand three straight?")
    heater_calls = [c for c in t.calls if c.get("stream")]
    ctx = json.loads(heater_calls[0]["messages"][-1]["content"])
    assert set(ctx) == {"fan_question"}            # no verdict, no claim result
    assert "BEFORE the Ref" in heater_calls[0]["messages"][0]["content"]
    assert out["heater_text"] == "HOT HAND IS REAL, I can FEEL it!"
    assert out["heater_reaction"] == HEATER_FALLBACK[out["verdict"]]


@pytest.mark.parametrize("line", ["The Ref says NOT SUPPORTED, folks!", "It SURVIVED the checks!",
                                  "No registered test, so just my opinion!"])
def test_heater_take_that_mentions_the_ref_falls_back(view, tmp_path, line):
    t = FakeTransport(heater=line)
    out = Dialogue(view, EvidenceLedger(tmp_path / "l.jsonl"), llm(tmp_path, t)).turn("hot hand three straight?")
    assert out["heater_text"] == HEATER_TAKE_FALLBACK
    assert out["sources"]["heater"].startswith("TEMPLATE (guard rejected Ref mention")


def test_no_test_question_take_says_nothing_about_tests_and_reaction_does(view, tmp_path):
    out = Dialogue(view, EvidenceLedger(tmp_path / "l.jsonl"), None).turn("Who has the best sneakers?")
    assert out["claim_id"] == "NONE" and out["heater_text"] == HEATER_TAKE_FALLBACK
    assert take_mentions_ref(out["heater_text"]) == []
    assert "no registered test" in out["heater_reaction"]
