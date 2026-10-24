# Weather trading execution audit — 2026-09-05

Live execution is paused. The original service was stopped and disabled from boot. No new orders were placed during this audit. At 03:16 UTC the exchange returned zero open orders. Earlier there were four unfilled bot sell orders at 94–95 cents; they subsequently appeared as canceled. The audit did not cancel those sells.

## Evidence and reconciliation

The legacy paper ledger recorded $2,420,153.37 realized profit between September 4 01:20 and 07:23 UTC, across 108 buys and 22 sells. Paper execution filled every maker target immediately without an opposing order or depth check. This invalidates those paper results as evidence of profitability.

The live journal contains 44 order submissions. Exchange trade history confirms 79 fills belonging to those journaled orders: 25 buy orders totaling $34.988386 gross and two sell orders totaling $7.3898 gross. Submission prices were not fill prices: a Paris sell submitted at 1 cent actually filled at 98 cents. The old ledger did not record realized PnL from sales.

For the tokens traded by the bot, the Data API reports $22.3537 realized loss on closed positions and $6.5722 current unrealized loss. These numbers include any external activity in the same tokens, and are not a bot-only or whole-wallet return. A separate NYC NO position is outside the bot's journaled trades. Forty historical order-detail lookups are no longer available, so full order lifecycle reconstruction remains incomplete; confirmed trade records remain available. Eight inventory differences between bot net buys and current positions correspond to tokens with closed-position records. External fills and fees also prevent attributing the entire wallet PnL to this bot.

Remote evidence is in `/root/weather-audit-backups/reconciliation/`: original exchange trades, attributed fills, open orders, historical order lookup results, current/closed positions, wallet activity, token totals, and summary. The original source and ledgers are backed up in `/root/weather-audit-backups/pre-fix-20260905.tar.gz`. Credentials were excluded from the archive.

## Repairs

- Validate and sort full books by best bid/ask; an ask without bids has no liquidation value. Missing or malformed books fail closed.
- Paper fills require crossing actual opposing depth. Partial fills consume depth, obey the limit and available cash, and use actual simulated execution prices. Maker quotes are not assumed to fill. Marking uses bid depth, with unfillable inventory conservatively valued at zero.
- Legacy paper ledgers cannot be loaded by the repaired broker. Fresh runs use `data/paper_v2_ledger.json`.
- Exit decisions receive fresh forecast probabilities instead of market midpoints; missing weather probabilities or bids suppress exits. Cash/exposure is refreshed after settlement and exits.
- Entries are priced against executable asks, enforce both edge hurdles, and cannot consume the scan limit with expired events.
- City exposure resolves canonical city identity from persistent metadata or titles. Existing market/contract costs count toward caps, as do other approvals in the same batch. Unknown exposure and unavailable risk data block entries. New live buys are blocked while a buy order is outstanding; only one new buy is accepted per execution batch to allow API state to catch up. A $5 per-entry cap is applied.
- Live execution and live entries each require an explicit enable flag. Failed open-order lookups block execution. Rejected orders are not recorded as success. Accepted submissions go into an `orders` collection with limit price and status, not simulated fill fields. Tick rounding preserves limit direction.
- Small collateral balances always convert from base units. Position queries paginate. The legacy PnL is explicitly marked incomplete rather than silently rewritten as an authoritative return.
- Wrong-day and incomplete forecasts are rejected. Provider labels identify Open-Meteo point forecasts with fixed uncertainty.
- Automatic paper settlement requires the market's final resolved token outcome, not estimated weather or reanalysis.
- Forecast probabilities, source, target day, bracket asks and vetoes are recorded to `data/forecast_audit.jsonl` for later calibration checks.
- Dashboard identifies live execution as paused, uses the configured paper ledger, and excludes legacy submissions from its fill display.

## Validation and limits

37 tests passed in the droplet's existing Python environment. Tests cover phantom maker profits, ask-only books, book sorting, partial fills, depth reuse, cash limits, existing exposure, disabled live execution, rejected orders, tick rounding, duplicate suppression, official settlement, wrong-day forecasts, and daemon probability/balance wiring. A separate paper-only cycle fetched a real Chicago forecast, METAR and book quotes and completed with no qualifying trades and unchanged $1,000 cash.

These checks validate repaired mechanics, not a profitable forecast model. The paper simulator does not model maker queue fills, fees, latency or market impact; its result is not a net executable return. Fixed forecast uncertainty and hand-set station adjustments remain uncalibrated. Resolution-station mappings need contract-by-contract validation before considering live reactivation. Historical paper profits must not be combined with the fresh run. Full legacy wallet accounting remains an audit artifact rather than a repaired PnL claim.

## Operation

- `weathernext-trader.service`: stopped and disabled; `LIVE_TRADING_ENABLED=false` and `LIVE_ENTRIES_ENABLED=false` persist in configuration.
- `weathernext-paper.service`: separate paper-only forward run, every 30 minutes, capped at $5 per simulated entry. It logs to the system journal and uses the fresh v2 paper ledger.
- `weathernext-web.service`: live-wallet dashboard, with execution marked paused.
- Read-only reconciliation: `python scripts/reconcile.py --output /root/weather-audit-backups/reconciliation-NEW` from the project root.

No live restart, deposits, position liquidation, or redemption was performed. Live trading should only be reconsidered after real forward observations and final market outcomes establish calibration and execution quality.

## First full forward cycle

The separate paper service completed its first 15-event cycle at 03:22:55 UTC. It wrote 15 forecast records and simulated nine buys, leaving $968.21 cash and $989.62 total equity under conservative bid-depth marks. The $10.38 initial markdown is unrealized, not a settled loss or a reliable performance estimate. It makes the cost of crossing spreads visible instead of manufacturing maker-exit profits. The dashboard's HTTP data endpoint was verified to return `live_trading_enabled: false` and the legacy-accounting warning. The live wallet snapshot was refreshed read-only; no order was submitted.
