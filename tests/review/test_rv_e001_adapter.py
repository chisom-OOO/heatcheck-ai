"""Reviewer probes of the E-001 read-only adapters (heatcheck/markets/adapters @ 38b66e5).

Edge cases beyond Experience's own A4/A5 tests. Each test states the expected behaviour; a
failure is a reviewer FINDING against the adapter (expected vs actual in the message).
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from heatcheck.markets.adapters import kalshi, polymarket
from heatcheck.markets.adapters.common import (
    AdapterError,
    Capture,
    overtime_convention,
    propose_mapping,
)
from heatcheck.markets.adapters.live import check_request

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_e001_bundle", ROOT / "tests" / "experience" / "make_e001_bundle.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

# PM_BOOK.timestamp is 1794067200050 ms = 2026-11-07T16:00:00.050Z
CAP = Capture(source="rv", fetch_start_utc="2026-11-07T16:00:00Z",
              received_utc="2026-11-07T16:00:00.100Z", data_mode="SYNTHETIC")
GAME = B.GAME_ID


def raw(obj) -> bytes:
    return B.payload_bytes(obj)


def pm_market():
    return polymarket.parse_market(raw(B.PM_MARKET), CAP)


def pm_book(cap=CAP, **changes):
    b = copy.deepcopy(B.PM_BOOK)
    b.update(changes)
    return polymarket.parse_book(raw(b), cap, market=pm_market(), contract_id=B.PM_TOKEN_HOME,
                                 game_id=GAME, paused=None)


def k_market():
    return kalshi.parse_market(raw(B.K_MARKET), CAP)


def refused(fn, *a, **k) -> AdapterError | None:
    try:
        out = fn(*a, **k)
    except AdapterError as exc:
        return exc
    return out  # returned a record: not refused


def test_control_fixture_book_parses_ok():
    q = pm_book()
    assert q["body"]["status"] == "OK"
    assert q["body"]["provider_time_utc"] == "2026-11-07T16:00:00.050Z"


# ------------------------------------------------------------------ units

@pytest.mark.parametrize("price", ["0.537", "0.0053", "0.005"])
def test_rv_e_u1_off_tick_price_refused(price):
    """Market tick 0.01. '0.0053' is a cents value divided by 100 twice."""
    out = refused(pm_book, bids=[{"price": price, "size": "10"}])
    assert isinstance(out, AdapterError), (
        f"EXPECTED refusal of off-tick price {price}; ACTUAL stored level "
        f"{out['body']['levels'] if isinstance(out, dict) else out}")


def test_rv_e_u2_zero_size_level_refused():
    out = refused(pm_book, bids=[{"price": "0.52", "size": "0"}])
    assert isinstance(out, AdapterError), "EXPECTED refusal of size 0; ACTUAL stored a level"


@pytest.mark.parametrize("price", ["-0.5", " 0.52", "0.52 ", "5.2e-1", "0,52", "0.5200000"])
def test_rv_e_u3_malformed_price_strings_refused(price):
    out = refused(pm_book, bids=[{"price": price, "size": "10"}])
    assert isinstance(out, AdapterError), f"EXPECTED refusal of {price!r}; ACTUAL stored"


def test_rv_e_u4_kalshi_off_tick_refused():
    bad = {"orderbook_fp": {"yes_dollars": [["0.5150", "10.00"]], "no_dollars": []}}
    out = refused(kalshi.parse_book, raw(bad), CAP, market=k_market(),
                  contract_id=f"{B.K_TICKER}:yes", game_id=GAME, paused=None)
    assert isinstance(out, AdapterError), "EXPECTED refusal of 0.5150 on a 0.01 tick; ACTUAL stored"


# ------------------------------------------------------------------ timestamps and staleness

def test_rv_e_t1_epoch_seconds_mistaken_for_ms_refused():
    """'1794067200' is epoch SECONDS (2026-11-07T16:00:00Z); read as ms it is 1970-01-21."""
    out = refused(pm_book, timestamp="1794067200")
    assert isinstance(out, AdapterError), (
        f"EXPECTED refusal (implausible provider time); ACTUAL provider_time_utc="
        f"{out['body']['provider_time_utc']} status={out['body']['status']}")


def test_rv_e_t2_provider_time_after_receipt_refused():
    out = refused(pm_book, timestamp="1794085200050")  # +5 h: local time stored as UTC
    assert isinstance(out, AdapterError), (
        f"EXPECTED refusal; ACTUAL provider {out['body']['provider_time_utc']} > received "
        f"{out['body']['received_utc']}, status {out['body']['status']}")


def test_rv_e_s1_two_hour_old_book_not_ok():
    out = refused(pm_book, timestamp="1794060000050")  # 2 h before receipt
    status = out["body"]["status"] if isinstance(out, dict) else "REFUSED"
    assert status != "OK", "EXPECTED STALE or refusal for a 2 h old book; ACTUAL status OK"


def test_rv_e_s2_day_long_fetch_window_refused():
    cap = Capture(source="rv", fetch_start_utc="2026-11-06T16:00:00Z",
                  received_utc="2026-11-07T16:00:00.100Z", data_mode="SYNTHETIC")
    out = refused(pm_book, cap=cap)
    assert isinstance(out, AdapterError) or out["body"]["status"] != "OK", \
        "EXPECTED refusal or non-OK for a 24 h fetch; ACTUAL status OK"


@pytest.mark.parametrize("ts", ["2026-11-07T16:00:00+00:00", "2026-11-07T16:00:00z",
                                "2026-11-07 16:00:00Z", "1794067200"])
def test_rv_e_t3_noncanonical_capture_times_refused(ts):
    cap = Capture(source="rv", fetch_start_utc=ts, received_utc="2026-11-07T16:00:00.100Z",
                  data_mode="SYNTHETIC")
    assert isinstance(refused(pm_book, cap=cap), AdapterError)


# ------------------------------------------------------------------ reversed outcomes, teams

def _k_rules():
    return kalshi.rules_text(raw(B.K_MARKET))


def test_rv_e_o1_no_contract_proposed_as_yes_team_win_refused():
    """Kalshi YES = Boston wins. Mapping the NO contract to 'Boston TEAM_WINS' reverses it."""
    m = k_market()
    no_label = next(o["label"] for o in m["body"]["outcomes"] if o["contract_id"].endswith(":no"))
    out = refused(propose_mapping, game_id=GAME, team_id="syn-team:BOS", market=m,
                  contract_id=f"{B.K_TICKER}:no", expected_label=no_label, rules_text=_k_rules())
    assert isinstance(out, AdapterError), (
        "EXPECTED refusal: NO contract proposed as the YES team's TEAM_WINS; ACTUAL PROPOSED "
        f"mapping team={out['body']['team_id']} contract={out['body']['contract_id']}")


def test_rv_e_o2_team_not_named_by_outcome_refused():
    """Outcome 'Celtics' proposed as TEAM_WINS for the Knicks' team id."""
    m = pm_market()
    out = refused(propose_mapping, game_id=GAME, team_id="syn-team:NYK", market=m,
                  contract_id=B.PM_TOKEN_HOME, expected_label="Celtics",
                  rules_text=B.PM_MARKET["description"])
    assert isinstance(out, AdapterError), (
        "EXPECTED refusal: team id is not the team the outcome names; ACTUAL PROPOSED "
        f"team={out['body']['team_id']} for outcome 'Celtics'")


def test_rv_e_o3_book_without_asset_id_refused():
    """The real CLOB book carries asset_id (live capture); a book without it cannot be
    tied to the token, so another token's book would be accepted."""
    out = refused(pm_book, asset_id=None)
    assert isinstance(out, AdapterError), "EXPECTED refusal; ACTUAL book accepted with no asset_id"


def test_rv_e_o4_misaligned_outcome_token_order_detectable():
    """Control: swapping outcome order changes which token carries which label."""
    mk = copy.deepcopy(B.PM_MARKET)
    mk["outcomes"] = '["Celtics", "Knicks"]'
    m = polymarket.parse_market(raw(mk), CAP)
    label = next(o["label"] for o in m["body"]["outcomes"] if o["contract_id"] == B.PM_TOKEN_HOME)
    assert label == "Knicks"  # parser follows the payload's own pairing, never position


# ------------------------------------------------------------------ overtime rules

@pytest.mark.parametrize("text, expected", [
    ("If the game is tied at the end of regulation, overtime periods count toward the result.",
     {"INCLUDES_OVERTIME", "UNKNOWN"}),
    ("Resolves on the final score including any overtime; it does not resolve at the end of "
     "regulation.", {"INCLUDES_OVERTIME", "UNKNOWN"}),
    ("Resolves on the score at the end of regulation only. Overtime is not included.",
     {"REGULATION_ONLY"}),
    ("The result will be determined based on the final score including any overtime periods.",
     {"INCLUDES_OVERTIME"}),
    ("Overtime does not count.", {"REGULATION_ONLY", "UNKNOWN"}),
    ("Includes OT.", {"INCLUDES_OVERTIME", "UNKNOWN"}),
])
def test_rv_e_ot1_overtime_reading(text, expected):
    got = overtime_convention(text)
    assert got in expected, f"EXPECTED {sorted(expected)} for {text!r}; ACTUAL {got}"


def test_rv_e_ot2_overtime_unknown_on_real_kalshi_text():
    """Real captured Kalshi rules (experience/live-quote@8a52691) never mention overtime."""
    text = ("If Indiana wins the Denver vs Indiana Pro Basketball game originally scheduled for "
            "Nov 7, 2026, then the market resolves to Yes.")
    assert overtime_convention(text) == "UNKNOWN"


# ------------------------------------------------------------------ read-only allowlist

@pytest.mark.parametrize("url", [
    "https://clob.polymarket.com/book/../order",
    "https://clob.polymarket.com/book%2F..%2Forder",
    "https://clob.polymarket.com/bookkeeping",
    "https://gamma-api.polymarket.com/marketsX/admin",
    "https://api.elections.kalshi.com/trade-api/v2/markets/../portfolio/orders",
    "https://api.elections.kalshi.com/trade-api/v2/events/../portfolio/balance",
])
def test_rv_e_r1_allowlist_prefix_bypass_refused(url):
    out = None
    try:
        out = check_request("GET", url)
    except AdapterError:
        return
    pytest.fail(f"EXPECTED refusal of {url}; ACTUAL allowed (host {out})")


@pytest.mark.parametrize("url", [
    "https://gamma-api.polymarket.com@evil.example/markets",
    "https://evil.example/?h=clob.polymarket.com/book",
    "http://clob.polymarket.com/book",
    "https://clob.polymarket.com:8443/book",
    "https://CLOB.polymarket.com./book",
])
def test_rv_e_r2_host_tricks_refused(url):
    with pytest.raises(AdapterError):
        check_request("GET", url)


def test_rv_e_r3_replay_reads_only_bundle(tmp_path, monkeypatch):
    """Replay of the committed bundle with every socket entry point disabled."""
    import socket

    from heatcheck.markets.adapters.replay import replay_bundle

    def refuse(*a, **k):
        raise AssertionError("network")
    for n in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, n, refuse)
    recs = replay_bundle(ROOT / "tests" / "fixtures" / "quotes" / "e001")
    assert recs and {r["record_type"] for r in recs} >= {"VENUE_MARKET", "QUOTE"}
    assert json.dumps(recs)  # serialisable
