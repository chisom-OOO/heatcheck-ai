"""Build the E-001 SYNTHETIC quote fixture bundle at tests/fixtures/quotes/e001/.

Every venue payload here is INVENTED in the venue's documented shape. It was carried over
from the Experience build's ``server/venue_fixtures.py`` (ZIP heatcheck-experience.zip,
sha256 c646c751454b696228e706f9035394f29ad2660802cdc1b6d11b49845f537a90) and adjusted
as noted in the bundle manifest. Nothing was fetched from Polymarket or Kalshi.

    uv run python tests/experience/make_e001_bundle.py [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from heatcheck.contracts.bundle import build_manifest, load_bundle, write_bundle  # noqa: E402
from heatcheck.contracts.records import sha256_hex  # noqa: E402
from heatcheck.markets.adapters.common import ADAPTER_VERSION, envelope  # noqa: E402
from heatcheck.markets.adapters.replay import CAPTURE_LOG_VERSION, derive  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "quotes" / "e001"
MODE = "SYNTHETIC"
GAME_ID = "syn:FIX-G0001"
HOME, AWAY = "syn-team:BOS", "syn-team:NYK"
RIGHTS = (
    "SYNTHETIC: invented payload in the venue's documented response shape, authored for "
    "HeatCheck tests. Not a capture; contains no venue data, so no venue terms were checked "
    "or apply. Freely redistributable within this repository."
)

K_TICKER = "KXNBAGAME-FIX26NOV08NYKBOS-BOS"
PM_SLUG = "fixture-nba-nyk-bos-2026-11-08"
PM_TOKEN_HOME = "222002"

PM_MARKET = {
    "id": "fixture-pm-1",
    "version": "v2",
    "question": "Knicks vs. Celtics",
    "events": [{"id": "fixture-pm-event-1"}],
    "outcomes": '["Knicks", "Celtics"]',
    "clobTokenIds": None,
    "positionIds": ["111001", PM_TOKEN_HOME],
    "gameStartTime": "2026-11-08 00:30:00+00",
    "endDateIso": "2026-11-08",
    "description": (
        "This market resolves to the team that wins the game, including any overtime. "
        "If the game is postponed, the market stays open until it is played; if cancelled, "
        "it resolves 50-50."
    ),
    "orderPriceMinTickSize": 0.01,
    "active": True,
    "closed": False,
    "acceptingOrders": True,
}
PM_BOOK = {
    "market": "0xfixture",
    "asset_id": PM_TOKEN_HOME,
    "timestamp": "1794067200050",
    "hash": "fixture",
    "bids": [{"price": "0.52", "size": "900"}, {"price": "0.53", "size": "410"}],
    "asks": [{"price": "0.58", "size": "700"}, {"price": "0.57", "size": "350"}],
    "tick_size": "0.01",
    "min_order_size": "5",
    "last_trade_price": "0.55",
}
K_MARKET = {
    "market": {
        "ticker": K_TICKER,
        "event_ticker": "KXNBAGAME-FIX26NOV08NYKBOS",
        "title": "New York Knicks at Boston Celtics: Winner?",
        "yes_sub_title": "Boston Celtics",
        "rules_primary": (
            "If the Boston Celtics win the New York Knicks vs Boston Celtics game scheduled for "
            "Nov 8, 2026, including any overtime, then the market resolves to Yes."
        ),
        "rules_secondary": (
            "If the game is postponed, the market remains open until the rescheduled game is "
            "played. If the game is cancelled, the market resolves per the exchange's "
            "cancellation rules."
        ),
        "occurrence_datetime": "2026-11-08T00:30:00Z",
        "status": "active",
        "tick_size_dollars": "0.01",
    }
}
K_BOOK = {
    "orderbook_fp": {
        "yes_dollars": [["0.5100", "300.00"], ["0.5200", "120.00"]],
        "no_dollars": [["0.4000", "200.00"], ["0.4200", "80.00"]],
    }
}


def payload_bytes(obj: dict) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build() -> tuple[dict, bytes, dict[str, bytes]]:
    pm_m, pm_b, k_m, k_b = (payload_bytes(p) for p in (PM_MARKET, PM_BOOK, K_MARKET, K_BOOK))
    sha = {name: sha256_hex(b) for name, b in
           (("pm_m", pm_m), ("pm_b", pm_b), ("k_m", k_m), ("k_b", k_b))}
    authored = "AUTHORED, not fetched; shape of "
    captures = [
        {"venue": "POLYMARKET", "kind": "MARKET", "payload_sha256": sha["pm_m"],
         "source": authored + f"GET https://gamma-api.polymarket.com/markets/slug/{PM_SLUG}",
         "fetch_start_utc": "2026-11-07T15:59:59.500Z", "received_utc": "2026-11-07T15:59:59.640Z"},
        {"venue": "POLYMARKET", "kind": "BOOK", "payload_sha256": sha["pm_b"],
         "market_payload_sha256": sha["pm_m"],
         "source": authored + f"GET https://clob.polymarket.com/book?token_id={PM_TOKEN_HOME}",
         "fetch_start_utc": "2026-11-07T16:00:00Z", "received_utc": "2026-11-07T16:00:00.120Z",
         "target": {"game_id": GAME_ID, "team_id": HOME, "contract_id": PM_TOKEN_HOME,
                    "expected_label": "Celtics"}},
        {"venue": "KALSHI", "kind": "MARKET", "payload_sha256": sha["k_m"],
         "source": authored + f"GET https://api.elections.kalshi.com/trade-api/v2/markets/{K_TICKER}",
         "fetch_start_utc": "2026-11-07T16:00:01Z", "received_utc": "2026-11-07T16:00:01.210Z"},
        {"venue": "KALSHI", "kind": "BOOK", "payload_sha256": sha["k_b"],
         "market_payload_sha256": sha["k_m"],
         "source": authored
         + f"GET https://api.elections.kalshi.com/trade-api/v2/markets/{K_TICKER}/orderbook",
         "fetch_start_utc": "2026-11-07T16:00:01.300Z", "received_utc": "2026-11-07T16:00:01.450Z",
         "target": {"game_id": GAME_ID, "team_id": HOME, "contract_id": f"{K_TICKER}:yes",
                    "expected_label": "YES (Boston Celtics)"}},
    ]
    log = {"capture_log_version": CAPTURE_LOG_VERSION, "data_mode": MODE,
           "adapter_version": ADAPTER_VERSION, "captures": captures,
           "note": "SYNTHETIC capture log: every time and payload in it is invented."}
    log_b = payload_bytes(log)
    log_sha = sha256_hex(log_b)

    raw = {f"raw/{s}.json": b for s, b in
           ((sha["pm_m"], pm_m), (sha["pm_b"], pm_b), (sha["k_m"], k_m), (sha["k_b"], k_b),
            (log_sha, log_b))}

    def snapshot(s: str, data: bytes, provider: str, source: str, schema: str, when: str) -> dict:
        return envelope("RAW_SNAPSHOT", s, MODE, {
            "snapshot_sha256": s, "provider": provider, "source": source,
            "redacted_params": {}, "retrieved_utc": when, "byte_count": len(data),
            "media_type": "application/json", "schema_version": schema,
            "rights_note": RIGHTS, "bundle_path": f"raw/{s}.json",
        })

    schemas = {"POLYMARKET": ("polymarket", "polymarket-gamma/v2", "polymarket-clob-book"),
               "KALSHI": ("kalshi", "kalshi-trade-api/v2", "kalshi-trade-api/v2")}
    payloads = {sha["pm_m"]: pm_m, sha["pm_b"]: pm_b, sha["k_m"]: k_m, sha["k_b"]: k_b}
    records = []
    for c in captures:
        provider, m_schema, b_schema = schemas[c["venue"]]
        schema = m_schema if c["kind"] == "MARKET" else b_schema
        records.append(snapshot(c["payload_sha256"], payloads[c["payload_sha256"]], provider,
                                c["source"], schema, c["received_utc"]))
    records.append(snapshot(log_sha, log_b, "heatcheck", "tests/experience/make_e001_bundle.py",
                            CAPTURE_LOG_VERSION, "2026-11-07T16:00:01.450Z"))
    records.append(envelope("GAME", GAME_ID, MODE, {
        "game_id": GAME_ID, "season": "2026-27", "competition": "REGULAR_SEASON",
        "provider_ids": {"experience_fixture": "FIX-G0001"},
        "home_team_id": HOME, "away_team_id": AWAY,
        "scheduled_tip_utc": "2026-11-08T00:30:00Z", "status": "SCHEDULED",
        "source_snapshot_ids": [log_sha],
    }))
    records.extend(derive(log, payloads))

    notes = (
        "E-001 SYNTHETIC FALLBACK. No live or recorded capture was made: live Polymarket/Kalshi "
        "GET requests were not authorised for this session, so G12 stays NOT_RUN. There is no "
        "original capture time; every fetch_start/received/provider time is invented "
        "(2026-11-07T15:59:59.5Z..16:00:01.45Z) and lies before the bundle was built. "
        "Payloads carried over from the Experience ZIP server/venue_fixtures.py "
        "(zip sha256 c646c751454b696228e706f9035394f29ad2660802cdc1b6d11b49845f537a90) with "
        "these changes: Polymarket market gains events[0].id (event_id is required); "
        "Polymarket book timestamp re-authored to 2026-11-07T16:00:00.050Z and "
        "last_trade_price added to prove it is not stored as a level; Kalshi book drops the "
        "non-venue _provider_time field. Game syn:FIX-G0001 (provider id FIX-G0001) is an "
        "Experience-authored schedule reference, not a Research canonical game; real team "
        "names appear only inside invented payload text. Levels are DIRECT as authored; no "
        "complement, midpoint or spread is stored. Mappings are PROPOSED for Max to verify."
    )
    manifest, body = build_manifest(
        records,
        bundle_id="e001-syn-quote-fixture-1",
        created_by_role="EXPERIENCE",
        created_utc="2026-11-07T16:30:00Z",
        producer={"tool": "tests/experience/make_e001_bundle.py", "version": "1",
                  "adapter_version": ADAPTER_VERSION},
        notes=notes,
    )
    return manifest, body, raw


def main() -> int:
    manifest, body, raw = build()
    if "--check" in sys.argv:
        on_disk, _ = load_bundle(OUT)
        same_raw = all((OUT / rel).read_bytes() == data for rel, data in raw.items())
        if on_disk != manifest or (OUT / "records.jsonl").read_bytes() != body or not same_raw:
            print("FAIL: committed E-001 bundle differs from generator output")
            return 1
        print(f"PASS: E-001 bundle reproducible, records_sha256={manifest['records_sha256']}")
        return 0
    write_bundle(OUT, manifest, body, raw)
    load_bundle(OUT)
    print(f"wrote {OUT.relative_to(ROOT)} records_sha256={manifest['records_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
