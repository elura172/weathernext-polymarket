"""
Continuous Background Trading Daemon & Scheduler.
Runs autonomous cycles matching WeatherNext 3 update cadences:
- Phase 1: Oracle Settlement & Position Expirations
- Phase 2: Convergence Monitoring & Maker Exit Executions
- Phase 3: Market Discovery & New Positive-EV Entries
- Phase 4: Ledger Persistence & Portfolio Telemetry
"""
import time
import json
from pathlib import Path
import signal
import sys
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from tabulate import tabulate
from config import cfg
from models import ExecutionMode
from polymarket.gamma_client import GammaClient
from polymarket.clob_client import ClobMarketClient
from forecast.public_fallback import PublicFallbackProvider
from forecast.weathernext import WeatherNextProvider
from forecast.nowcasting import MetarNowcaster
from registry.stations import resolve_station
from strategy.pricer import BracketPricer
from strategy.edge import EdgeCalculator
from strategy.risk import RiskManager
from strategy.convergence import ConvergenceEngine
from execution.paper_broker import PaperBroker
from execution.live_broker import LiveBroker
from execution.resolver import OracleResolver

handlers = [logging.StreamHandler(sys.stdout)]
if sys.stdout.isatty():
    handlers.append(logging.FileHandler("/root/polymarket-weathernext/data/daemon.log"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=handlers
)
logger = logging.getLogger("WeatherDaemon")

class WeatherTradingDaemon:
    def __init__(self, interval_seconds: int = 3600, max_events: int = 20):
        self.interval = interval_seconds
        self.max_events = max_events
        self.running = True

        # Signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

        # Clients
        self.gamma = GammaClient()
        self.clob = ClobMarketClient()
        self.wn = WeatherNextProvider()
        self.fallback = PublicFallbackProvider()
        self.nowcaster = MetarNowcaster()

        if cfg.MODE == ExecutionMode.LIVE:
            self.broker = LiveBroker()
        else:
            self.broker = PaperBroker()

    def _handle_exit(self, signum, frame):
        logger.info("Shutdown signal received. Stopping daemon gracefully...")
        self.running = False

    def get_active_weather_provider(self):
        return self.wn if self.wn.initialized else self.fallback

    def run_cycle(self, cycle_num: int):
        logger.info(f"=== DAEMON CYCLE #{cycle_num} START ({cfg.MODE.value} MODE) ===")
        portfolio = self.broker.get_portfolio_state()
        logger.info(f"Portfolio Balance: ${portfolio.total_portfolio_value_usdc:,.2f} | Cash: ${portfolio.cash_usdc:,.2f} | Open Positions: {len(portfolio.positions)}")

        provider = self.get_active_weather_provider()
        provider_name = "WeatherNext 3" if self.wn.initialized else "Open-Meteo point forecast (fixed uncertainty)"
        logger.info(f"Using Provider: {provider_name}")

        # PHASE 1: Oracle Settlement Check for Past-Dated Contracts
        self._check_settlements()

        # Price once, using actual forecasts, then refresh balances after exits.
        portfolio = self.broker.get_portfolio_state()
        all_signals, probabilities = self._collect_signals(portfolio, provider)
        self._check_convergence_exits(portfolio, probabilities)
        portfolio = self.broker.get_portfolio_state()
        approved = RiskManager.filter_and_scale_signals(all_signals, portfolio)
        if approved:
            self.broker.execute_signals(approved)
        if isinstance(self.broker, PaperBroker):
            self.broker.mark_to_market()

        # Refresh Portfolio State
        updated_port = self.broker.get_portfolio_state()
        logger.info(f"=== CYCLE #{cycle_num} FINISHED | Value: ${updated_port.total_portfolio_value_usdc:,.2f} | Cash: ${updated_port.cash_usdc:,.2f} ===")

    def _check_settlements(self):
        """Resolves positions whose contract dates have finalized."""
        logger.info("Phase 1: Checking positions for oracle settlement...")
        portfolio = self.broker.get_portfolio_state()
        if not portfolio.positions:
            logger.info("Phase 1: No open positions to settle.")
            return

        if cfg.MODE == ExecutionMode.LIVE:
            if hasattr(self.broker, "settle_resolved_positions"):
                self.broker.settle_resolved_positions()
        else:
            for tok_id, pos in list(portfolio.positions.items()):
                winner = self.gamma.get_resolved_token_outcome(pos.market_id, tok_id)
                if winner is not None:
                    self.broker.resolve_position(tok_id, None, 0, 0, is_winner=winner)

    def _check_convergence_exits(self, portfolio, probabilities):
        """Monitors open positions for convergence exits."""
        if not portfolio.positions:
            logger.info("Phase 2: No active positions to monitor.")
            return

        logger.info(f"Phase 2: Monitoring {len(portfolio.positions)} active positions for convergence...")
        quotes = {}
        for tok_id, pos in portfolio.positions.items():
            bid, ask, mid = self.clob.get_market_quote(tok_id)
            quotes[tok_id] = (bid, ask, mid)

        exit_signals = ConvergenceEngine.evaluate_convergence_orders(portfolio, quotes, probabilities)
        if exit_signals:
            logger.info(f"Executing {len(exit_signals)} Convergence Exit Orders...")
            self.broker.execute_signals(exit_signals)

    def _collect_signals(self, portfolio, provider):
        """Collect fresh weather probabilities and executable entry signals."""
        logger.info(f"Phase 3: Scanning top {self.max_events} weather events for positive EV...")
        contracts = self.gamma.fetch_active_weather_events(max_pages=3)
        if not contracts:
            logger.info("No active weather events found.")
            return [], {}

        contracts = [c for c in contracts if c.target_date >= datetime.now(ZoneInfo(c.timezone)).date().isoformat()]
        all_signals, probabilities = [], {}
        held = set(portfolio.positions)
        selected = list(contracts[:self.max_events])
        selected_ids = {c.event_id for c in selected}
        for contract in contracts:
            if contract.event_id not in selected_ids and any(b.token_id_yes in held or b.token_id_no in held for b in contract.brackets):
                selected.append(contract)
        for contract in selected:
            # A forecast for an expired local day must not create a new entry.
            if contract.target_date < datetime.now(ZoneInfo(contract.timezone)).date().isoformat():
                continue
            forecast = provider.get_hourly_forecast(
                station_icao=contract.station_icao,
                lat=contract.lat,
                lon=contract.lon,
                target_date=contract.target_date,
                unit=contract.unit
            )
            if not forecast:
                continue

            station = resolve_station(contract.station_icao) or resolve_station(contract.city)
            nowcast = self.nowcaster.fetch_station_nowcast(station, contract.target_date) if station else None

            contract.brackets = BracketPricer.price_contract_brackets(contract, forecast, nowcast=nowcast)
            if nowcast and nowcast.is_today:
                logger.info(
                    f"[{contract.city}] METAR: {nowcast.latest_temp_c}°C ({nowcast.latest_temp_f}°F), "
                    f"Today Max: {nowcast.today_max_c}°C, Sky: {nowcast.cloud_cover}, "
                    f"Microclimate: {station.microclimate_bias_c:+.1f}°C"
                )

            for bracket in contract.brackets:
                probabilities[bracket.token_id_yes] = bracket.model_prob
                probabilities[bracket.token_id_no] = 1.0 - bracket.model_prob
                # Entries must be evaluated at an executable ask, not Gamma marks.
                _, ask, _ = self.clob.get_market_quote(bracket.token_id_yes)
                bracket.market_price_yes = ask
            audit = {
                "timestamp": datetime.now(timezone.utc).isoformat(), "mode": cfg.MODE.value,
                "event_id": contract.event_id, "title": contract.event_title,
                "station": contract.station_icao, "target_date": contract.target_date,
                "unit": contract.unit.value, "source": forecast.source_model,
                "forecast_max": forecast.t_max, "forecast_min": forecast.t_min,
                "sigma": forecast.ensemble_std,
                "brackets": [{"token_id": b.token_id_yes, "market_id": b.market_id,
                              "label": b.label, "model_probability": b.model_prob,
                              "ask": b.market_price_yes, "veto": b.veto_reason}
                             for b in contract.brackets]
            }
            audit_path = Path(cfg.PAPER_LEDGER_PATH).parent / "forecast_audit.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a") as handle:
                handle.write(json.dumps(audit) + "\n")
            signals = EdgeCalculator.compute_signals(contract, portfolio.cash_usdc)
            all_signals.extend(signals)

        return all_signals, probabilities

    def start(self):
        logger.info(f"Starting Weather Trading Daemon (Interval: {self.interval}s)")
        cycle = 1
        while self.running:
            try:
                self.run_cycle(cycle)
            except Exception as e:
                logger.error(f"Error during daemon cycle #{cycle}: {e}", exc_info=True)

            cycle += 1
            if not self.running:
                break

            logger.info(f"Sleeping for {self.interval} seconds until next hourly cycle...")
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

        logger.info("Daemon has shut down cleanly.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Weather Trading Daemon")
    parser.add_argument("--interval", type=int, default=3600, help="Loop interval in seconds (default: 3600 = 1 hour)")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--limit", type=int, default=15, help="Max events to evaluate per cycle")
    args = parser.parse_args()

    daemon = WeatherTradingDaemon(interval_seconds=args.interval, max_events=args.limit)
    if args.once:
        daemon.run_cycle(1)
    else:
        daemon.start()
