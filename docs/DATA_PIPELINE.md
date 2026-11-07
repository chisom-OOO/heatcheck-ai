# HeatCheck data pipeline specification

Implementation handoff for heatcheck-nba/1. Pro Research owns NBA ingestion, normalization and point-in-time features. Pro Experience owns public venue readers and replay capture. Max owns schemas, access to labels, the run ledger and integration. This is a proposed build. Source documentation was checked; coverage, account permissions, live endpoints and model performance require execution.

## 1. First reproducible NBA dataset

Start with a single completed regular season, 2023–24, from the [NBA bulk data repository](https://github.com/shufinskiy/nba_data). Record its exact Git commit and the chosen season files. Select one play-by-play provider for the entire first pass. Inspect column names and identifiers before mapping them. List every included game and every excluded game with a reason. Expand to adjacent seasons only after reconciliation. A single season proves plumbing; evaluate whether the retained sample supports each proposed test.

Derive game outcomes and shot sequences from that snapshot. Reconcile home/away, tip time and final scores against a second source when available. Use the [BALLDONTLIE games API](https://docs.balldontlie.io/) with a user-provided key and date filters, following its pagination cursor to exhaustion. Check the account tier before requesting richer fields. Cache successful responses. If the cross-check is unavailable, mark coverage unverified. Avoid silently stitching shots from a different provider into a missing game. Record data-use and redistribution terms separately for each upstream dataset; distribute a fetch manifest or invented fixtures when raw redistribution rights are unclear.

## 2. Storage contract

| Dataset | Identity and minimum fields | Consumer |
|---|---|---|
| Raw snapshot | provider, upstream revision or endpoint and redacted parameters, retrieval UTC, payload hash, byte count, schema version, rights note | Replay and audit |
| Game | canonical game ID, season and competition, provider IDs, home/away team IDs, scheduled tip UTC, game status | Joins and chronological splits |
| Event | game ID, provider event ID and revision, period, clock, sequence, team/player IDs, action, event time if available | Shot research |
| Feature row | prediction target ID, cutoff UTC or game sequence, feature version, maximum input availability, source hashes | Discoverer and Challenger |
| Restricted label | target ID, outcome, finalization or first observation time, revision | Custodian and Referee |
| Venue mapping | game ID, venue event/market ID, outcome/token or ticker, team, rules reference and hash, overtime/cancellation terms, mapping status | Read-only adapters |
| Quote | mapping ID, quote side, decimal price, size when present, source timestamp if supplied, received UTC, raw hash, live/recorded mode | Comparison and replay |

Store immutable payloads by content hash, normalize into versioned tables, and write a run manifest listing input and output hashes, transformation revision, record counts and exclusions. First implementation can use local files plus SQLite. Publish validated batches in one transaction. Commit pagination checkpoints only after the page and records are durable. Retry rate limits with bounded backoff and Retry-After. A changed payload under the same upstream ID creates a revision. Rerunning the same snapshot must leave row counts and values identical.

## 3. Two research cutoffs

**Before tip.** Predict a named team's game-win probability at a declared UTC cutoff. Rolling features may use only games with outcomes available by that cutoff. Prior rest and home/away are useful first features. Keep the target game's final score, closing quotes after cutoff, corrected future statistics and retrospectively inferred injuries out of feature tables.

**Before a shot.** Order events by the provider's documented sequence within game and period; the clock can tie. Derive pre-shot margin and previous attempts from strictly earlier events. Issue a missing value or exclude the row when ordering is unresolved. The current shot's result, assist attribution and resulting score belong downstream. For bulk history lacking original publication times tag availability assumptions and report retrospective results. Start prospective collection separately.

Split chronologically by whole game into fit, tuning, calibration and sealed final sets. Save game-ID lists and hash them before testing. Discoverer and Challenger use development views. Max's custodian reserves final underlying IDs in a persistent exposure ledger before evaluating the frozen claim family. Report score and sample size against the same-games baseline, including coverage losses. A venue comparison never upgrades a research verdict.

## 4. Market observations for a specific NBA forecast

1. Start with a canonical scheduled NBA game and a team-win target. Retrieve candidate metadata on each venue independently. For Polymarket use public event/market metadata, resolve outcome to token ID, then read the book using that token. For Kalshi find the matching event/market ticker, identify what YES means from the contract and read its order book. Inspect the response version and documented units. [Polymarket market data](https://docs.polymarket.com/market-data/overview) · [Polymarket books](https://docs.polymarket.com/market-data/prices-order-books) · [Kalshi books](https://docs.kalshi.com/api-reference/market/get-market-orderbook)
2. Match league, both teams, scheduled game and outcome semantics. Record overtime, postponement and cancellation rules. Ambiguous or incompatible contracts receive a reason and no numerical comparison. An absent listing on one venue must leave the other venue usable.
3. Parse price strings as decimals in the documented unit and preserve the raw side. For a binary Kalshi book reporting complementary bids, a NO bid of 0.42 implies a YES ask of 0.58. Mark it as derived. For Polymarket use the selected outcome's actual bid and ask. Omit midpoint if either side is missing or the book is crossed. Preserve the spread. Synthetic example: bid 0.52, ask 0.56, midpoint 0.54, model forecast 0.59 gives a descriptive difference of +5 percentage points.
4. For historical evaluation select the latest eligible quote actually observed by the forecast cutoff. For a current display show forecast time and quote time independently. Configure and record a freshness threshold before the demo; stale, unavailable or future quotes receive explicit status. Never reconstruct a historical book from today's price. Store timestamped observations now for prospective comparisons. Use a labeled recorded snapshot for offline replay and report its original capture time.

## 5. First handoff and acceptance

Pro Research delivers one frozen season manifest, reconciliation report, canonical game/event tables, restricted labels, and a feature builder that can replay one named game. Pro Experience delivers one fixture per venue and optional dated public captures with clearly stated provenance. Max joins one forecast and one valid quote by outcome and cutoff, then demonstrates the same run offline. If market data is unavailable, finish the NBA research run and show the reason on the comparison card.

| Check | Evidence required before declaring a pass |
|---|---|
| Coverage and identity | Actual distinct games/events, missing fields, duplicate IDs, unmatched schedules and score discrepancies. Quarantine contradictions. |
| Time integrity | Change the target outcome and a later event. The earlier feature vector must be byte-identical. A quote received after the cutoff must be ineligible. |
| Replay and recovery | Interrupt ingestion after one page, resume, run twice, compare logical table hashes. Preserve a corrected upstream record as a separate revision. |
| Market semantics | Test reversed outcomes, same teams on different dates, overtime mismatch, cents versus dollars, missing side and stale book. Assert exact normalized values or refusal reasons. |
| Research isolation | Assert disjoint game IDs, held-out access restrictions and a persistent final exposure receipt. Distinguish synthetic fixtures, retrospective NBA history, recorded markets and live observations in every output. |

Record commands, environment, snapshot IDs and actual test output in the run evidence. All checks above start NOT_RUN. No purchase, paid feed, credential or friend's code is required for the offline fixture path.
