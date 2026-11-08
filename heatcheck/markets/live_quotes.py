"""Read-only venue prices for the games in a ``heatcheck-live-forecast/1`` file.

The forecast is ``p_home_win``, so for each game this captures the HOME team's win contract:

    Polymarket  GET gamma /markets/slug/nba-<away>-<home>-<US Eastern date>, then its CLOB book
    Kalshi      GET /events/KXNBAGAME-<YYMONDD><AWAY><HOME>, /markets/<event>-<HOME>, then its
                orderbook

The slug and ticker are derived from the forecast's own game; nothing is searched for or
guessed. A candidate is MATCHED only when every identity check in ``match_polymarket`` /
``match_kalshi`` passes (same date and tip, both teams, the home team's outcome). Otherwise it is
REJECTED with the check that failed, NOT_FOUND when the derived slug/ticker does not exist, or
ERROR. Every GET body is kept under ``raw/`` with its fetch-start and received time (404s and
rejected payloads too); each MATCHED contract becomes a ``heatcheck-records/1`` bundle built by
the existing ``capture.build``, so its quote is re-derivable offline.

A forecast whose ``source`` says SAMPLE is hand-made. Its game list can be used to exercise this
tool, and the output says so on every level; no forecast value is copied into the output.

    python -m heatcheck.markets.live_quotes validate <forecasts.json>
    python -m heatcheck.markets.live_quotes capture <forecasts.json> <out_dir>
    python -m heatcheck.markets.live_quotes index <out_dir>     # board.mappings.json for the page

``capture`` writes the index itself when at least one contract MATCHED.
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.parse
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from heatcheck.contracts.bundle import load_bundle, write_bundle
from heatcheck.contracts.records import sha256_hex
from heatcheck.markets.adapters import capture, polymarket
from heatcheck.markets.adapters.common import (
    ADAPTER_VERSION,
    AdapterError,
    load_payload,
    team_tricode,
    teams_named,
)
from heatcheck.markets.adapters.live import ReadOnlyClient, utc_now
from heatcheck.markets.adapters.replay import CAPTURE_LOG_VERSION

FORMAT = "heatcheck-live-forecast/1"
QUOTES_FORMAT = "heatcheck-live-quotes/1"
DATA_MODE = "RECORDED_MARKET"  # stored exactly as received; replayed offline from raw/
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_GAME_RE = re.compile(r"^nba:(\d{3})(\d{2})\d{5}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_COMPETITION = {"001": "PRESEASON", "002": "REGULAR_SEASON", "004": "PLAYOFFS", "005": "PLAY_IN"}
_MON = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
# Kalshi's expected_expiration_time is not the tip (tip 22:00Z -> 01:00Z on the recorded game);
# it must fall after the tip and within this window, or the game is not certain.
KALSHI_EXPIRY_WINDOW = timedelta(hours=6)
RIGHTS_NOTE = (
    "RECORDED public market data from an unauthenticated read-only GET, stored exactly as "
    "received. Venue terms of use for redistribution were NOT reviewed by Experience; kept in "
    "this private repository. Confirm venue terms before any public release."
)


class Reject(Exception):
    """An identity check failed: the candidate is not certainly this game, team and outcome."""


# ---------------------------------------------------------------- forecast file


def parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.match(value):
        raise ValueError(f"{value!r} is not a UTC timestamp ending in Z")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _num(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def is_sample(doc: dict[str, Any]) -> bool:
    """True when ``source.results`` starts with SAMPLE (docs/LIVE_FORECAST_FORMAT.md)."""
    src = doc.get("source")
    return isinstance(src, dict) and str(src.get("results", "")).startswith("SAMPLE")


def validate_forecast(doc: Any) -> list[str]:
    """Every rule of the shared format that the file breaks; empty when it is valid.

    Mirrors Max's ``heatcheck.contracts.live_forecast`` rules that matter here; ``load_forecast``
    also runs Max's validator itself when this checkout has it."""
    if not isinstance(doc, dict):
        return ["the file is not a JSON object"]
    errs: list[str] = []
    if doc.get("format") != FORMAT:
        errs.append(f"format is {doc.get('format')!r}, not {FORMAT!r}")
    if doc.get("label") != "DESCRIPTIVE FORECAST":
        errs.append("label must be exactly 'DESCRIPTIVE FORECAST'")
    if not isinstance(doc.get("model"), str) or not doc["model"]:
        errs.append("model must be a non-empty string")
    inputs = doc.get("inputs_used")
    if not isinstance(inputs, list) or not inputs or not all(isinstance(i, str) for i in inputs):
        errs.append("inputs_used must be a non-empty list of strings")
    sample = is_sample(doc)
    src = doc.get("source")
    if not isinstance(src, dict):
        errs.append("source must be an object")
    else:
        for k in ("results", "fetched_utc", "sha256", "cross_check"):
            if not isinstance(src.get(k), str) or not src[k]:
                errs.append(f"source.{k} must be a non-empty string")
        cc = str(src.get("cross_check", ""))
        if cc != "NOT_RUN" and not cc.startswith("balldontlie"):
            errs.append("source.cross_check must be NOT_RUN or start with 'balldontlie'")
        if sample:  # the literal SAMPLE or a real value, never an invented hash or time
            if src.get("fetched_utc") != "SAMPLE" and not _UTC_RE.match(str(src.get("fetched_utc"))):
                errs.append("source.fetched_utc of a SAMPLE must be 'SAMPLE' or a UTC Z time")
            if src.get("sha256") != "SAMPLE" and not _HEX64.match(str(src.get("sha256"))):
                errs.append("source.sha256 of a SAMPLE must be 'SAMPLE' or a real sha256")
        else:
            if any("SAMPLE" in s for s in _strings(src)):
                errs.append("a non-sample file may not say SAMPLE anywhere in source")
            try:
                parse_utc(src.get("fetched_utc"))
            except ValueError as exc:
                errs.append(f"source.fetched_utc: {exc}")
            if not _HEX64.match(str(src.get("sha256"))):
                errs.append("source.sha256 must be 64 lowercase hex characters")
    try:
        cutoff = parse_utc(doc.get("data_cutoff_utc"))
    except ValueError as exc:
        errs.append(f"data_cutoff_utc: {exc}")
        cutoff = None
    bt = doc.get("backtest_2024_25")
    if not isinstance(bt, dict):
        errs.append("backtest_2024_25 must be an object")
    else:
        if not _num(bt.get("log_loss")) or bt["log_loss"] < 0:
            errs.append("backtest_2024_25.log_loss must be a number >= 0")
        if not _num(bt.get("brier")) or not 0 <= bt["brier"] <= 1:
            errs.append("backtest_2024_25.brier must be a number in [0, 1]")
        if not isinstance(bt.get("games"), int) or isinstance(bt["games"], bool) or bt["games"] < 0:
            errs.append("backtest_2024_25.games must be an integer >= 0")
    games = doc.get("games")
    if not isinstance(games, list) or not games:
        errs.append("games must be a non-empty list")
        return errs
    seen: set[str] = set()
    for i, g in enumerate(games):
        where = f"games[{i}]"
        if not isinstance(g, dict):
            errs.append(f"{where} is not an object")
            continue
        gid = g.get("game_id")
        m = _GAME_RE.match(gid) if isinstance(gid, str) else None
        if not m:
            errs.append(f"{where}.game_id {gid!r} is not nba:<10-digit NBA game id>")
        elif m.group(1) not in _COMPETITION:
            errs.append(f"{where}.game_id {gid!r} has an unsupported season-type prefix")
        if gid in seen:
            errs.append(f"{where}.game_id {gid!r} is repeated")
        seen.add(gid)
        try:
            tip = parse_utc(g.get("tip_utc"))
            if cutoff is not None and not cutoff < tip:
                errs.append(f"{where}: data_cutoff_utc is not before tip_utc {g['tip_utc']}")
        except ValueError as exc:
            errs.append(f"{where}.tip_utc: {exc}")
        tris = {}
        for side in ("home", "away"):
            tid = g.get(f"{side}_team_id")
            try:
                tris[side] = team_tricode(tid) if isinstance(tid, str) else None
                if tris[side] is None or not tid.startswith("nba-team:"):
                    raise AdapterError("not an nba-team: id")
            except AdapterError:
                errs.append(f"{where}.{side}_team_id {tid!r} is not a known nba-team: id")
                tris[side] = None
                continue
            name = g.get(f"{side}_team")
            if not isinstance(name, str) or teams_named(name) != {tris[side]}:
                errs.append(f"{where}.{side}_team {name!r} does not name {tris[side]} alone")
        if tris.get("home") and tris.get("home") == tris.get("away"):
            errs.append(f"{where}: home and away are the same team")
        if not _num(g.get("p_home_win")) or not 0 <= g["p_home_win"] <= 1:
            errs.append(f"{where}.p_home_win must be a probability in [0, 1]")
        for k in ("elo_home", "elo_away"):
            if not _num(g.get(k)):
                errs.append(f"{where}.{k} must be a number")
    return errs


def max_validator():
    """Max's ``parse_live_forecast`` when this checkout has it (integrate since 5bb5f73)."""
    try:
        from heatcheck.contracts.live_forecast import parse_live_forecast
    except ImportError:
        return None
    return parse_live_forecast


def load_forecast(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = Path(path).read_bytes()
    doc = load_payload(raw)
    errs = validate_forecast(doc)
    parse = max_validator()
    if parse is not None:
        try:
            parse(raw)
        except ValueError as exc:  # LiveForecastError is a ValueError
            errs.append(f"Max's validator: {exc}")
    if errs:
        raise AdapterError(f"{path} breaks {FORMAT}: " + "; ".join(errs))
    return doc, raw


# ---------------------------------------------------------------- game identity


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))


def us_eastern_date(t: datetime) -> date:
    """The US Eastern calendar date of a UTC instant (US DST rules in force since 2007)."""
    y = t.year
    dst_on = datetime.combine(_nth_sunday(y, 3, 2), time(7), UTC)  # 02:00 EST
    dst_off = datetime.combine(_nth_sunday(y, 11, 1), time(6), UTC)  # 02:00 EDT
    return (t - timedelta(hours=4 if dst_on <= t < dst_off else 5)).date()


def game_ref(g: dict[str, Any]) -> dict[str, Any]:
    tip = parse_utc(g["tip_utc"])
    return {"game_id": g["game_id"], "tip_utc": g["tip_utc"], "tip": tip,
            "home_team_id": g["home_team_id"], "away_team_id": g["away_team_id"],
            "home": team_tricode(g["home_team_id"]), "away": team_tricode(g["away_team_id"]),
            "local_date": us_eastern_date(tip)}


def polymarket_slug(ref: dict[str, Any]) -> str:
    return f"nba-{ref['away'].lower()}-{ref['home'].lower()}-{ref['local_date'].isoformat()}"


def kalshi_event_ticker(ref: dict[str, Any]) -> str:
    d = ref["local_date"]
    return f"KXNBAGAME-{d:%y}{_MON[d.month - 1]}{d:%d}{ref['away']}{ref['home']}"


def _names(value: Any) -> set[str]:
    return teams_named(value) if isinstance(value, str) else set()


def _pm_start(value: Any) -> datetime:
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(\+00(:00)?|Z)", str(value))
    if not m:
        raise Reject(f"gameStartTime {value!r} is missing or not a UTC time")
    return datetime.fromisoformat(f"{m[1]}T{m[2]}+00:00")


def match_polymarket(m: Any, ref: dict[str, Any]) -> str:
    """Return the home team's outcome label, or raise Reject naming the failed check."""
    if not isinstance(m, dict):
        raise Reject("payload is not a market object")
    home, away = ref["home"], ref["away"]
    if m.get("slug") != polymarket_slug(ref):
        raise Reject(f"slug {m.get('slug')!r} is not {polymarket_slug(ref)!r}")
    if m.get("sportsMarketType") != "moneyline":
        raise Reject(f"sportsMarketType {m.get('sportsMarketType')!r} is not 'moneyline'")
    if m.get("active") is not True or m.get("closed") is not False:
        raise Reject(f"market not open (active={m.get('active')!r}, closed={m.get('closed')!r})")
    start = _pm_start(m.get("gameStartTime"))
    if start != ref["tip"]:
        raise Reject(f"gameStartTime {start:%Y-%m-%dT%H:%M:%SZ} is not the tip {ref['tip_utc']}")
    if _names(m.get("question")) != {home, away}:
        raise Reject(f"question {m.get('question')!r} does not name exactly {away} and {home}")
    try:
        outcomes = polymarket._json_list(m.get("outcomes"), "outcomes")
    except AdapterError as exc:
        raise Reject(str(exc)) from None
    named = [_names(o) for o in outcomes]
    if len(outcomes) != 2 or sorted(map(sorted, named)) != sorted([[home], [away]]):
        raise Reject(f"outcomes {outcomes!r} are not one {home} outcome and one {away} outcome")
    return outcomes[named.index({home})]


def match_kalshi(event: Any, market: Any, ref: dict[str, Any]) -> str:
    """Return the home team's YES label, or raise Reject naming the failed check."""
    home, away = ref["home"], ref["away"]
    ev_ticker = kalshi_event_ticker(ref)
    e = event.get("event") if isinstance(event, dict) else None
    m = market.get("market") if isinstance(market, dict) else None
    if not isinstance(e, dict) or not isinstance(m, dict):
        raise Reject("payload has no event or market object")
    if e.get("event_ticker") != ev_ticker:
        raise Reject(f"event_ticker {e.get('event_ticker')!r} is not {ev_ticker!r}")
    if _names(e.get("title")) != {home, away}:
        raise Reject(f"event title {e.get('title')!r} does not name exactly {away} and {home}")
    if m.get("ticker") != f"{ev_ticker}-{home}" or m.get("event_ticker") != ev_ticker:
        raise Reject(f"market {m.get('ticker')!r} is not {ev_ticker}-{home}")
    if m.get("market_type") != "binary":
        raise Reject(f"market_type {m.get('market_type')!r} is not 'binary'")
    if m.get("status") not in ("active", "open"):
        raise Reject(f"market status {m.get('status')!r} is not open")
    if _names(m.get("yes_sub_title")) != {home} or _names(m.get("title")) != {home}:
        raise Reject(f"YES side {m.get('yes_sub_title')!r} / title {m.get('title')!r} "
                     f"does not name {home} alone")
    try:
        expiry = parse_utc(m.get("expected_expiration_time"))
    except ValueError as exc:
        raise Reject(f"expected_expiration_time: {exc}") from None
    if not ref["tip"] < expiry <= ref["tip"] + KALSHI_EXPIRY_WINDOW:
        raise Reject(f"expected_expiration_time {m['expected_expiration_time']} is not within "
                     f"{KALSHI_EXPIRY_WINDOW} after the tip {ref['tip_utc']}")
    return f"YES ({m['yes_sub_title']})"


# ---------------------------------------------------------------- capture


class _Store:
    """GETs through the read-only client; keeps every body and its times."""

    def __init__(self, client: ReadOnlyClient, raw_dir: Path):
        self.client, self.raw_dir, self.requests = client, raw_dir, []
        raw_dir.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> tuple[int, bytes, dict[str, Any]]:
        status, body, start, received = self.client.get(url)
        sha = sha256_hex(body)
        (self.raw_dir / f"{sha}.json").write_bytes(body)
        entry = {"source": f"GET {url}", "http_status": status, "payload_sha256": sha,
                 "fetch_start_utc": start, "received_utc": received}
        self.requests.append(entry)
        return status, body, entry


def _book_target(ref, contract, label):
    return {"game_id": ref["game_id"], "team_id": ref["home_team_id"],
            "contract_id": contract, "expected_label": label}


def _polymarket(store: _Store, ref: dict[str, Any]) -> tuple[dict, list[dict]]:
    slug = polymarket_slug(ref)
    res: dict[str, Any] = {"venue": "POLYMARKET", "slug": slug}
    status, body, m_entry = store.get(f"{capture.GAMMA}/markets/slug/{slug}")
    res["market_get"] = m_entry
    if status == 404:
        return {**res, "status": "NOT_FOUND",
                "reason": f"no Polymarket market at slug {slug!r} (HTTP 404); nothing else "
                          "was searched"}, []
    if status != 200:
        return {**res, "status": "ERROR", "reason": f"HTTP {status} for the market"}, []
    try:
        m = load_payload(body)
        label = match_polymarket(m, ref)
        outcomes = polymarket._json_list(m.get("outcomes"), "outcomes")
        ids_field = "positionIds" if m.get("version") == "v2" else "clobTokenIds"
        tokens = polymarket._json_list(m.get(ids_field), ids_field)
        if len(tokens) != len(outcomes):
            raise Reject(f"{ids_field} and outcomes differ in length")
    except (Reject, AdapterError) as exc:
        return {**res, "status": "REJECTED", "reason": str(exc)}, []
    contract = tokens[outcomes.index(label)]
    status, _, b_entry = store.get(f"{capture.CLOB}/book?token_id={urllib.parse.quote(contract)}")
    res["book_get"] = b_entry
    if status != 200:
        return {**res, "status": "ERROR", "reason": f"HTTP {status} for the book"}, []
    caps = [{"venue": "POLYMARKET", "kind": "MARKET", **m_entry},
            {"venue": "POLYMARKET", "kind": "BOOK", **b_entry,
             "market_payload_sha256": m_entry["payload_sha256"],
             "target": _book_target(ref, contract, label)}]
    return {**res, "status": "MATCHED", "contract_id": contract, "label": label}, caps


def _kalshi(store: _Store, ref: dict[str, Any]) -> tuple[dict, list[dict]]:
    ev_ticker = kalshi_event_ticker(ref)
    ticker = f"{ev_ticker}-{ref['home']}"
    res: dict[str, Any] = {"venue": "KALSHI", "ticker": ticker}
    status, e_body, e_entry = store.get(f"{capture.KALSHI}/events/{ev_ticker}")
    res["event_get"] = e_entry
    if status == 404:
        return {**res, "status": "NOT_FOUND",
                "reason": f"no Kalshi event {ev_ticker!r} (HTTP 404); nothing else was searched"}, []
    if status != 200:
        return {**res, "status": "ERROR", "reason": f"HTTP {status} for the event"}, []
    status, m_body, m_entry = store.get(f"{capture.KALSHI}/markets/{ticker}")
    res["market_get"] = m_entry
    if status == 404:
        return {**res, "status": "NOT_FOUND",
                "reason": f"no Kalshi market {ticker!r} (HTTP 404); nothing else was searched"}, []
    if status != 200:
        return {**res, "status": "ERROR", "reason": f"HTTP {status} for the market"}, []
    try:
        label = match_kalshi(load_payload(e_body), load_payload(m_body), ref)
    except (Reject, AdapterError) as exc:
        return {**res, "status": "REJECTED", "reason": str(exc)}, []
    status, _, b_entry = store.get(f"{capture.KALSHI}/markets/{ticker}/orderbook")
    res["book_get"] = b_entry
    if status != 200:
        return {**res, "status": "ERROR", "reason": f"HTTP {status} for the orderbook"}, []
    contract = f"{ticker}:yes"
    caps = [{"venue": "KALSHI", "kind": "MARKET", **m_entry},
            {"venue": "KALSHI", "kind": "BOOK", **b_entry,
             "market_payload_sha256": m_entry["payload_sha256"],
             "target": _book_target(ref, contract, label)}]
    return {**res, "status": "MATCHED", "contract_id": contract, "label": label}, caps


def _game_reference(ref: dict[str, Any], source: str) -> dict[str, Any]:
    digits = ref["game_id"].split(":", 1)[1]
    yy = int(digits[3:5])
    return {"game_id": ref["game_id"], "season": f"20{yy:02d}-{(yy + 1) % 100:02d}",
            "competition": _COMPETITION[digits[:3]], "provider_ids": {"nba_com": digits},
            "home_team_id": ref["home_team_id"], "away_team_id": ref["away_team_id"],
            "scheduled_tip_utc": ref["tip_utc"], "status": "SCHEDULED",
            "reference_source": source}


def _bundle(out: Path, name: str, store: _Store, ref, caps, source, notes, created) -> list[dict]:
    """Write one bundle from the stored bodies; return its records (validated on reload)."""
    bundle = out / name  # kept short: Windows paths stop at 260 characters
    raw_dir = bundle / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for c in caps:
        sha = c["payload_sha256"]
        (raw_dir / f"{sha}.json").write_bytes((store.raw_dir / f"{sha}.json").read_bytes())
    log = {"capture_log_version": CAPTURE_LOG_VERSION, "data_mode": DATA_MODE,
           "adapter_version": ADAPTER_VERSION, "game_reference": _game_reference(ref, source),
           "captures": caps, "note": notes}
    log_bytes = (json.dumps(log, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (raw_dir / f"{sha256_hex(log_bytes)}.json").write_bytes(log_bytes)
    manifest, body, raw = capture.build(bundle, RIGHTS_NOTE, notes, created)
    write_bundle(bundle, manifest, body, raw)
    return load_bundle(bundle)[1]


def _quote_summary(records: list[dict], contract: str, tip: datetime) -> dict[str, Any]:
    (q,) = [r["body"] for r in records
            if r["record_type"] == "QUOTE" and r["body"]["contract_id"] == contract]
    (mp,) = [r["body"] for r in records
             if r["record_type"] == "VENUE_MAPPING" and r["body"]["contract_id"] == contract]
    bids = [lv["price"] for lv in q["levels"] if lv["side"] == "BID"]
    asks = [lv["price"] for lv in q["levels"] if lv["side"] == "ASK"]
    return {"quote_status": q["status"], "quote_status_reason": q["status_reason"],
            "best_bid": max(bids, key=float) if bids else None,
            "best_ask": min(asks, key=float) if asks else None,
            "levels_derivation": sorted({lv["derivation"] for lv in q["levels"]}),
            "provider_time_utc": q["provider_time_utc"],
            "fetch_start_utc": q["fetch_start_utc"], "received_utc": q["received_utc"],
            "received_before_tip": parse_utc(q["received_utc"]) < tip,
            "mapping_status": mp["status"], "overtime_convention": mp["overtime_convention"]}


def run(forecast_path: Path, out: Path, client: ReadOnlyClient | None = None) -> dict[str, Any]:
    """Capture every game in the forecast file into ``out``; return the summary written."""
    doc, raw = load_forecast(forecast_path)
    sample = is_sample(doc)
    out.mkdir(parents=True, exist_ok=True)
    store = _Store(client or ReadOnlyClient(), out / "raw")
    started = utc_now()
    f_sha = sha256_hex(raw)
    kind = "a hand-made SAMPLE forecast file (not Research's)" if sample else "the forecast file"
    source = (f"game_id, tip_utc and team ids from {kind} {Path(forecast_path).as_posix()} "
              f"sha256 {f_sha}; source.results: {doc['source']['results']}")
    pending = []
    games = []
    for g in doc["games"]:
        ref = game_ref(g)
        venues = []
        for fn in (_polymarket, _kalshi):
            try:
                res, caps = fn(store, ref)
            except AdapterError as exc:  # network failure, refused URL, size cap
                res, caps = {"venue": fn.__name__[1:].upper(), "status": "ERROR",
                             "reason": str(exc)}, []
            res["team_id"] = ref["home_team_id"]
            res["outcome"] = "TEAM_WINS (home team)"
            venues.append(res)
            if caps:
                pending.append((ref, res, caps))
        games.append({"game_id": ref["game_id"], "tip_utc": ref["tip_utc"],
                      "home_team_id": ref["home_team_id"], "away_team_id": ref["away_team_id"],
                      "home": ref["home"], "away": ref["away"],
                      "us_eastern_date": ref["local_date"].isoformat(), "venues": venues})
    finished = utc_now()
    created = finished[:19] + "Z"
    stamp = created.replace("-", "").replace(":", "")
    for ref, res, caps in pending:
        notes = (f"Live read-only capture for {ref['game_id']} ({ref['away']} at {ref['home']}, "
                 f"tip {ref['tip_utc']}), {res['venue']} contract {res['contract_id']} "
                 f"labelled {res['label']!r} = home team wins. Received "
                 f"{caps[0]['received_utc']} (market) and {caps[1]['received_utc']} (book), "
                 f"local clock. Game list: {source}. Mapping PROPOSED for Max to verify. "
                 + ("SAMPLE INPUT: the game list was hand-made; the venue prices are real. "
                    if sample else ""))
        short = {"POLYMARKET": "pm", "KALSHI": "kx"}[res["venue"]]
        name = f"{ref['game_id'].split(':')[1]}-{short}-{stamp[9:13]}"  # e.g. 0022600190-pm-2229
        try:
            records = _bundle(out, name, store, ref, caps, source, notes, created)
            res.update(_quote_summary(records, res["contract_id"], ref["tip"]), bundle=name)
        except (AdapterError, ValueError, OSError) as exc:
            res.update(status="ERROR", reason=f"record build refused: {exc}")
    counts: dict[str, int] = {}
    for g in games:
        for v in g["venues"]:
            counts[v["status"]] = counts.get(v["status"], 0) + 1
    summary = {
        "format": QUOTES_FORMAT,
        "label": "READ-ONLY VENUE PRICES" + (" FOR A SAMPLE GAME LIST" if sample else ""),
        "forecast_input": {"path": Path(forecast_path).as_posix(), "sha256": f_sha,
                           "is_sample": sample, "source": doc["source"],
                           "data_cutoff_utc": doc["data_cutoff_utc"]},
        "sample_warning": ("SAMPLE: the game list came from a hand-made file, not Research's "
                           "forecast. Prices are real venue data; no forecast value is copied "
                           "here.") if sample else None,
        "data_mode": DATA_MODE, "adapter_version": ADAPTER_VERSION,
        "outcome_captured": "home team wins (the forecast's p_home_win)",
        "run_started_utc": started, "run_finished_utc": finished,
        "counts": counts, "games": games, "requests": store.requests,
    }
    (out / "quotes.json").write_bytes(
        (json.dumps(summary, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return summary


INDEX_FORMAT = "heatcheck-quote-mappings/1"


def _best_levels(quote: dict[str, Any]) -> bool:
    sides = {lv["side"] for lv in quote["body"]["levels"]}
    return {"BID", "ASK"} <= sides


def write_index(run_dir: Path, name: str = "board") -> dict[str, Any]:
    """Write ``<run_dir>/<name>.mappings.json``: which venue mapping ids the run's bundles hold,
    for the demo page's market board. Ids, labels and statuses only, never prices; every number on
    a card comes from Max's /api/investigate, which reads the bundles themselves
    (``serve_dialogue --quote-bundle <run_dir>`` searches the directory for bundles).

    Pure over the run's bundles, so it is byte-reproducible. Returns the index."""
    run_dir = Path(run_dir)
    summary = load_payload((run_dir / "quotes.json").read_bytes())
    mappings = []
    for g in summary["games"]:
        for v in g["venues"]:
            if v.get("status") != "MATCHED" or "bundle" not in v:
                continue
            manifest, recs = load_bundle(run_dir / v["bundle"])
            markets = {r["record_id"]: r["body"] for r in recs if r["record_type"] == "VENUE_MARKET"}
            quotes = {r["body"]["mapping_id"]: r for r in recs if r["record_type"] == "QUOTE"}
            for r in recs:
                if r["record_type"] != "VENUE_MAPPING":
                    continue
                b = r["body"]
                mk = markets[b["venue_market_record_id"]]
                label = next(o["label"] for o in mk["outcomes"] if o["contract_id"] == b["contract_id"])
                mappings.append({"mapping_id": b["mapping_id"], "game_id": b["game_id"],
                                 "venue": mk["venue"], "contract_id": b["contract_id"],
                                 "team_id": b["team_id"], "label": label, "status": b["status"],
                                 "two_sided": b["mapping_id"] in quotes
                                 and _best_levels(quotes[b["mapping_id"]]),
                                 "bundle": v["bundle"], "records_sha256": manifest["records_sha256"]})
    if not mappings:
        raise AdapterError(f"{run_dir} has no MATCHED contract to index")
    index = {"format": INDEX_FORMAT, "run": run_dir.name,
             "captured": [summary["run_started_utc"], summary["run_finished_utc"]],
             "forecast_input": summary["forecast_input"],
             "note": ("Ids, labels and statuses as captured (PROPOSED until Max verifies them). "
                      "No prices: they come from /api/investigate."),
             "mappings": sorted(mappings, key=lambda m: (m["game_id"], m["venue"]))}
    (run_dir / f"{name}.mappings.json").write_bytes(
        (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return index


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "index":
        index = write_index(Path(argv[1]))
        print(f"PASS indexed {len(index['mappings'])} mappings in {argv[1]}/board.mappings.json")
        return 0
    if len(argv) == 2 and argv[0] == "validate":
        doc = load_payload(Path(argv[1]).read_bytes())
        errs = validate_forecast(doc)
        for e in errs:
            print(f"FAIL {e}")
        if not errs:
            print(f"PASS {argv[1]}: {FORMAT}, {len(doc['games'])} games"
                  + (", SAMPLE (hand-made)" if is_sample(doc) else ""))
        return 1 if errs else 0
    if len(argv) == 3 and argv[0] == "capture":
        s = run(Path(argv[1]), Path(argv[2]))
        if s["sample_warning"]:
            print(s["sample_warning"])
        for g in s["games"]:
            for v in g["venues"]:
                extra = (f"bid={v.get('best_bid')} ask={v.get('best_ask')} "
                         f"quote={v.get('quote_status')} received={v.get('received_utc')}"
                         if v["status"] == "MATCHED" else v.get("reason", ""))
                print(f"{g['game_id']} {g['away']}@{g['home']} {v['venue']:<10} "
                      f"{v['status']:<9} {extra}")
        print(f"counts {s['counts']}; wrote {argv[2]}/quotes.json")
        if s["counts"].get("MATCHED"):
            index = write_index(Path(argv[2]))
            print(f"indexed {len(index['mappings'])} mappings in {argv[2]}/board.mappings.json")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
