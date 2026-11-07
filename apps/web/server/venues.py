"""Read-only, venue-neutral market adapters: Polymarket and Kalshi.

Interface (every adapter): discover_markets(game), get_market_spec(market_ref), get_book(spec, outcome),
get_rule_source(spec), health(), capabilities().

Safety (tested in tests/test_venues.py):
  * only HTTPS GET to an allowlisted host + path prefix; no redirects followed; private/loopback
    resolution refused; response size capped; bounded retry honouring Retry-After on 429.
  * no order, signing, wallet, transfer or account endpoint exists in this module.
  * every payload is hashed and timestamped (fetch start / received) and kept raw.

Schema notes (from vendor docs read 7 Nov 2026; checked against the recorded capture
tests/fixtures/quotes/e001-recorded-0022600189 on 7 Nov 2026):
  Polymarket Gamma  GET https://gamma-api.polymarket.com/markets/slug/{slug} -> market object with
                    outcomes (JSON string), clobTokenIds (JSON string; these are the CLOB book token
                    ids), gameStartTime, description, orderPriceMinTickSize, active/closed/acceptingOrders.
                    The real capture was version v1. positionIds (documented for v2) is used only when
                    clobTokenIds is absent and is UNVERIFIED against a real payload.
  Polymarket CLOB   GET https://clob.polymarket.com/book?token_id=... -> {bids, asks, timestamp(ms), hash, tick_size}
  Kalshi            GET {base}/markets/{ticker} -> {market: {...}}
                    GET {base}/markets/{ticker}/orderbook -> {orderbook_fp: {yes_dollars, no_dollars}}; bids only.
"""
import hashlib
import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from . import quotes
from .quotes import PRICE_UNIT
from .timefmt import iso_z, parse_utc

ADAPTER_VERSION = "0.2-capture-2026-11-07"
MAX_RESPONSE = 2 * 1024 * 1024
# A provider timestamp later than our own receipt by more than this is a clock fault, not a quote.
PROVIDER_CLOCK_TOLERANCE_SECONDS = 5
ALLOW = {
    "gamma-api.polymarket.com": ("/markets/slug/", "/markets", "/events"),
    "clob.polymarket.com": ("/book",),
    "api.elections.kalshi.com": ("/trade-api/v2/markets", "/trade-api/v2/events"),
    "external-api.kalshi.com": ("/trade-api/v2/markets", "/trade-api/v2/events"),
}
KALSHI_BASE = os.environ.get("HEATCHECK_KALSHI_BASE", "https://api.elections.kalshi.com/trade-api/v2")


def utcnow():
    return datetime.now(UTC)


class VenueError(Exception):
    """status is one of the protocol-visible outcomes."""

    def __init__(self, status, reason, **extra):
        super().__init__(reason)
        self.status, self.reason, self.extra = status, reason, extra

    def as_dict(self):
        return {"status": self.status, "reason": self.reason, **self.extra}


def check_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https":
        raise VenueError("BLOCKED", f"only https is allowed, got {u.scheme!r}")
    if u.username or u.password or (u.port not in (None, 443)):
        raise VenueError("BLOCKED", "credentials or non-standard ports in URL are not allowed")
    host = (u.hostname or "").lower()
    if host not in ALLOW:
        raise VenueError("BLOCKED", f"host {host!r} is not on the read-only allowlist")
    if not any(u.path.startswith(p) for p in ALLOW[host]):
        raise VenueError("BLOCKED", f"path {u.path!r} is not an allowlisted public read endpoint")
    return host


def _assert_public(host):
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise VenueError("UNAVAILABLE", f"DNS failure for {host}: {e}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise VenueError("BLOCKED", f"{host} resolved to non-public address {ip}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VenueError("BLOCKED", f"redirect to {newurl!r} refused (HTTP {code})")


class UrllibTransport:
    """Live transport. Never sends cookies or credentials."""
    name = "live"

    def __init__(self, timeout=8):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_NoRedirect)

    def get(self, url):
        host = check_url(url)
        _assert_public(host)
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json",
                                                                  "User-Agent": "heatcheck-experience/0.1 read-only"})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                body = r.read(MAX_RESPONSE + 1)
                return r.status, dict(r.headers), body
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read(MAX_RESPONSE + 1) if e.fp else b""
        except VenueError:
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            raise VenueError("UNAVAILABLE", f"network error: {getattr(e, 'reason', e)}") from None


class FixtureTransport:
    """Serves authored payloads keyed by URL. Used for offline replay and tests.
    data_mode of its artifacts is whatever the fixture file declares (SYNTHETIC for authored ones).

    clock_utc is the authored fetch time reported for every response. Without it a replay would
    stamp today's wall clock as received_at_utc next to an authored provider_time, which is how
    BookSnapshot.json once showed provider_time 8 hours after its own receipt."""
    name = "fixture"

    def __init__(self, routes, data_mode="SYNTHETIC", captured_at=None, clock_utc=None):
        self.routes, self.data_mode, self.captured_at = routes, data_mode, captured_at
        self.clock_utc = parse_utc(clock_utc) if clock_utc else None

    def get(self, url):
        check_url(url)
        r = self.routes.get(url)
        if r is None:
            return 404, {}, b'{"error":"not found in fixture"}'
        if isinstance(r, tuple):
            return r
        return 200, {}, r if isinstance(r, bytes) else json.dumps(r).encode()


def fetch_json(transport, url, retries=3, max_sleep=5.0, sleep=time.sleep):
    """Bounded retry for 429/5xx; Retry-After honoured up to max_sleep. Returns (obj, provenance)."""
    attempt = 0
    clock = getattr(transport, "clock_utc", None)
    while True:
        attempt += 1
        start = clock or utcnow()
        status, headers, body = transport.get(url)
        received = clock or utcnow()
        if len(body) > MAX_RESPONSE:
            raise VenueError("MALFORMED", f"response over {MAX_RESPONSE} bytes")
        if status == 429 or 500 <= status < 600:
            if attempt > retries:
                raise VenueError("RATE_LIMITED" if status == 429 else "UNAVAILABLE",
                                 f"HTTP {status} after {attempt} attempts", url=url)
            ra = headers.get("Retry-After") or headers.get("retry-after")
            try:
                wait = float(ra) if ra is not None else 0.5 * 2 ** (attempt - 1)
            except ValueError:
                wait = 0.5 * 2 ** (attempt - 1)
            sleep(min(max(wait, 0.0), max_sleep))
            continue
        if status == 404:
            raise VenueError("NO_MATCH", "venue returned 404 for this identifier", url=url)
        if status != 200:
            raise VenueError("UNAVAILABLE", f"HTTP {status}", url=url)
        try:
            obj = json.loads(body, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        except ValueError as e:
            raise VenueError("MALFORMED", f"invalid JSON: {e}", url=url) from None
        prov = {"url": url, "fetch_start_utc": iso_z(start), "received_at_utc": iso_z(received),
                "clock": "authored fixture clock" if clock else "local system clock",
                "raw_hash": hashlib.sha256(body).hexdigest(), "bytes": len(body), "attempts": attempt,
                "transport": transport.name}
        return obj, prov


def _json_list(v, field):
    if v is None:
        return None
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            out = json.loads(v)
        except ValueError:
            raise VenueError("MALFORMED", f"{field} is not valid JSON") from None
        if not isinstance(out, list):
            raise VenueError("MALFORMED", f"{field} is not a list")
        return out
    raise VenueError("MALFORMED", f"{field} has unexpected type")


def _sha(text):
    return hashlib.sha256((text or "").encode()).hexdigest()


def _parse_time(s):
    if not s:
        return None
    try:
        if isinstance(s, (int, float)) or (isinstance(s, str) and s.isdigit()):
            return datetime.fromtimestamp(int(s) / 1000, tz=UTC)
        return datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None


# ------------------------------------------------------------------------------------- Polymarket

class PolymarketAdapter:
    venue = "polymarket"
    GAMMA = "https://gamma-api.polymarket.com"
    CLOB = "https://clob.polymarket.com"

    def __init__(self, transport):
        self.t = transport

    def capabilities(self):
        return {"venue": self.venue, "adapter_version": ADAPTER_VERSION, "read_only": True,
                "operations": ["market_by_slug", "book_by_token"], "trading": False,
                "discovery": "by explicit market slug; free-text search is not implemented"}

    def health(self):
        return {"venue": self.venue, "transport": self.t.name, **self.capabilities()}

    def discover_markets(self, game, slug=None):
        if not slug:
            raise VenueError("UNSUPPORTED", "Polymarket discovery needs an explicit market slug in this build")
        return [self.get_market_spec(slug)]

    def get_market_spec(self, slug):
        if not slug or "/" in slug or "?" in slug or len(slug) > 200:
            raise VenueError("MALFORMED", "invalid market slug")
        url = f"{self.GAMMA}/markets/slug/{urllib.parse.quote(slug)}"
        m, prov = fetch_json(self.t, url)
        if not isinstance(m, dict):
            raise VenueError("MALFORMED", "market payload is not an object")
        version = m.get("version") or ("v1" if m.get("clobTokenIds") else None)
        if version not in ("v1", "v2"):
            raise VenueError("UNSUPPORTED", f"market version {version!r} not supported")
        outcomes = _json_list(m.get("outcomes"), "outcomes")
        # clobTokenIds are the ids the CLOB /book endpoint takes (verified on a real v1 capture).
        if m.get("clobTokenIds"):
            ids = _json_list(m.get("clobTokenIds"), "clobTokenIds")
        elif version == "v2":
            ids = _json_list(m.get("positionIds"), "positionIds")   # unverified fallback
        else:
            ids = None
        if not outcomes or not ids or len(outcomes) != len(ids):
            raise VenueError("MALFORMED", "outcomes and token IDs missing or misaligned")
        rules = m.get("description") or ""
        tick = m.get("orderPriceMinTickSize")
        status = "OPEN" if (m.get("active") and not m.get("closed") and m.get("acceptingOrders", True)) else "PAUSED_MARKET"
        return {
            "venue_api_version": f"polymarket-gamma/{version}",
            "venue": self.venue,
            "market_id": str(m.get("id") or slug),
            "slug": slug,
            "event_id": str((m.get("events") or [{}])[0].get("id")) if m.get("events") else m.get("eventId"),
            "outcome_contract_ids": [{"label": str(o), "contract_id": str(i)} for o, i in zip(outcomes, ids, strict=True)],
            "title": m.get("question") or m.get("title") or "",
            "nba_event_identity": {"game_start_utc": m.get("gameStartTime"), "end_date": m.get("endDateIso") or m.get("endDate")},
            "rules_text": rules,
            "rules_hash": _sha(rules),
            "settlement_source": m.get("resolutionSource") or None,
            "outcome_convention": "each outcome has its own token; YES of an outcome token pays if that outcome wins",
            "price_quantity_grid": {"price_unit": PRICE_UNIT, "tick": str(tick) if tick is not None else None,
                                     "quantity_unit": "shares"},
            "capabilities": self.capabilities(),
            "market_status": status,
            "provenance": prov,
            "data_mode": "LIVE_MARKET" if self.t.name == "live" else self.t.data_mode,
        }

    def get_rule_source(self, spec):
        return {"rules_text": spec["rules_text"], "rules_hash": spec["rules_hash"], "source": spec["provenance"]["url"]}

    def get_book(self, spec, contract_id):
        if contract_id not in {o["contract_id"] for o in spec["outcome_contract_ids"]}:
            raise VenueError("NO_MATCH", "contract id is not one of this market's outcome tokens")
        url = f"{self.CLOB}/book?token_id={urllib.parse.quote(contract_id)}"
        b, prov = fetch_json(self.t, url)
        if not isinstance(b, dict):
            raise VenueError("MALFORMED", "book payload is not an object")
        if b.get("asset_id") not in (None, contract_id):
            raise VenueError("MALFORMED", "book asset_id does not match requested token")
        tick = b.get("tick_size") or spec["price_quantity_grid"]["tick"]
        try:
            norm = quotes.normalise_polymarket(b, tick=tick)
        except quotes.QuoteError as e:
            raise VenueError(e.status, str(e)) from None
        return _snapshot(self.venue, spec, contract_id, "outcome_token_bid_ask", norm, b.get("timestamp"), prov, self.t)


# ------------------------------------------------------------------------------------- Kalshi

class KalshiAdapter:
    venue = "kalshi"

    def __init__(self, transport, base=KALSHI_BASE):
        self.t, self.base = transport, base.rstrip("/")

    def capabilities(self):
        return {"venue": self.venue, "adapter_version": ADAPTER_VERSION, "read_only": True,
                "operations": ["market_by_ticker", "orderbook"], "trading": False,
                "discovery": "by explicit market ticker; event search is not implemented"}

    def health(self):
        return {"venue": self.venue, "transport": self.t.name, "base": self.base, **self.capabilities()}

    def discover_markets(self, game, ticker=None):
        if not ticker:
            raise VenueError("UNSUPPORTED", "Kalshi discovery needs an explicit market ticker in this build")
        return [self.get_market_spec(ticker)]

    def get_market_spec(self, ticker):
        if not ticker or not all(c.isalnum() or c in "-_." for c in ticker) or len(ticker) > 120:
            raise VenueError("MALFORMED", "invalid market ticker")
        url = f"{self.base}/markets/{ticker}"
        obj, prov = fetch_json(self.t, url)
        m = obj.get("market") if isinstance(obj, dict) else None
        if not isinstance(m, dict):
            raise VenueError("MALFORMED", "missing market object")
        rules = "\n".join(x for x in (m.get("rules_primary"), m.get("rules_secondary")) if x)
        status = m.get("status")
        return {
            "venue_api_version": "kalshi-trade-api/v2",
            "venue": self.venue,
            "market_id": m.get("ticker", ticker),
            "event_id": m.get("event_ticker"),
            "outcome_contract_ids": [{"label": "YES", "contract_id": f"{ticker}:yes", "yes_means": m.get("yes_sub_title")},
                                     {"label": "NO", "contract_id": f"{ticker}:no"}],
            "title": m.get("title", ""),
            "yes_sub_title": m.get("yes_sub_title"),
            "nba_event_identity": {"game_start_utc": m.get("occurrence_datetime") or m.get("expected_expiration_time"),
                                   "close_time": m.get("close_time")},
            "rules_text": rules,
            "rules_hash": _sha(rules),
            "settlement_source": (m.get("settlement_sources") or [None])[0] if isinstance(m.get("settlement_sources"), list) else None,
            "outcome_convention": "binary YES/NO; book returns YES bids and NO bids only; YES ask is derived as 1 - best NO bid",
            "price_quantity_grid": {"price_unit": PRICE_UNIT, "tick": m.get("tick_size_dollars") or "0.01",
                                     "quantity_unit": "contracts (fixed-point string)"},
            "capabilities": self.capabilities(),
            "market_status": "OPEN" if status in ("active", "open") else ("PAUSED_MARKET" if status else "UNKNOWN"),
            "provenance": prov,
            "data_mode": "LIVE_MARKET" if self.t.name == "live" else self.t.data_mode,
        }

    def get_rule_source(self, spec):
        return {"rules_text": spec["rules_text"], "rules_hash": spec["rules_hash"], "source": spec["provenance"]["url"]}

    def get_book(self, spec, contract_id):
        ticker = spec["market_id"]
        if contract_id != f"{ticker}:yes":
            raise VenueError("UNSUPPORTED", "comparisons are made against the YES contract; select the YES side")
        url = f"{self.base}/markets/{ticker}/orderbook"
        obj, prov = fetch_json(self.t, url)
        if not isinstance(obj, dict):
            raise VenueError("MALFORMED", "orderbook payload is not an object")
        if "orderbook_fp" not in obj:
            # Legacy integer-cent `orderbook` arrays are refused, not converted: heatcheck-records/1
            # accepts PROBABILITY_DOLLARS decimal strings only (docs/DATA_FORMAT.md).
            legacy = isinstance(obj.get("orderbook"), dict)
            raise VenueError("UNKNOWN_UNITS", "legacy integer-cent orderbook refused; only orderbook_fp "
                             f"({PRICE_UNIT} decimal strings) is accepted" if legacy
                             else "orderbook has no orderbook_fp")
        try:
            norm = quotes.normalise_kalshi(obj["orderbook_fp"], tick=spec["price_quantity_grid"]["tick"])
        except quotes.QuoteError as e:
            raise VenueError(e.status, str(e)) from None
        return _snapshot(self.venue, spec, contract_id, "yes_bid_and_derived_yes_ask", norm,
                         obj.get("_provider_time"), prov, self.t)


def _snapshot(venue, spec, contract_id, side, norm, provider_time, prov, transport):
    pt = _parse_time(provider_time)
    if pt is not None and pt.tzinfo is None:
        raise VenueError("MALFORMED", f"provider time {provider_time!r} has no UTC offset")
    received = parse_utc(prov["received_at_utc"])
    if pt is not None and (pt - received).total_seconds() > PROVIDER_CLOCK_TOLERANCE_SECONDS:
        raise VenueError("CLOCK_SKEW", f"provider_time {iso_z(pt)} is later than received_at_utc "
                         f"{prov['received_at_utc']} by more than {PROVIDER_CLOCK_TOLERANCE_SECONDS}s; "
                         "quote refused")
    snap = {
        "venue": venue,
        "market_id": spec["market_id"],
        "contract_id": contract_id,
        "normalized_side": side,
        "price_unit": PRICE_UNIT,
        "quantity_unit": spec["price_quantity_grid"]["quantity_unit"],
        "levels": {"bids": norm["bids"], "asks": norm["asks"]},
        "best_bid": norm["best_bid"], "best_ask": norm["best_ask"],
        "midpoint": norm["midpoint"], "midpoint_unavailable_reason": norm["midpoint_unavailable_reason"],
        "spread": norm["spread"], "crossed": norm["crossed"], "ask_is_derived": norm["ask_is_derived"],
        "liquidity_ids": [],
        "provider_time": iso_z(pt) if pt else None,
        "fetch_start_utc": prov["fetch_start_utc"],
        "received_at_utc": prov["received_at_utc"],
        "clock_uncertainty": "provider and local clocks not synchronised; book fetches across venues are not atomic",
        "raw_hash": prov["raw_hash"],
        "adapter_version": ADAPTER_VERSION,
        "status": "CROSSED_BOOK" if norm["crossed"] else ("ONE_SIDED" if norm["midpoint"] is None else "OK"),
        "data_mode": "LIVE_MARKET" if transport.name == "live" else transport.data_mode,
        "captured_at": getattr(transport, "captured_at", None),
        "source_url": prov["url"],
    }
    return snap


def adapter(venue, transport):
    if venue == "polymarket":
        return PolymarketAdapter(transport)
    if venue == "kalshi":
        return KalshiAdapter(transport)
    raise VenueError("UNSUPPORTED", f"no validated adapter for venue {venue!r}")
