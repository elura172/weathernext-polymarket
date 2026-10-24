"""
Unified CLI Runner for Polymarket Weather Intelligence & Trading Engine.
Supports scanning, pricing, signal generation, position management, and paper/live trading.
"""
import argparse
import logging
import sys
from tabulate import tabulate
from config import cfg
from models import ExecutionMode, OrderSide
from polymarket.gamma_client import GammaClient
from polymarket.clob_client import ClobMarketClient
from forecast.public_fallback import PublicFallbackProvider
from forecast.weathernext import WeatherNextProvider
from forecast.nowcasting import MetarNowcaster
from registry.stations import resolve_station
from strategy.pricer import BracketPricer
from strategy.edge import EdgeCalculator
from strategy.risk import RiskManager
from strategy.exit import ExitManager
from execution.paper_broker import PaperBroker
from execution.live_broker import LiveBroker
from execution.resolver import OracleResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WeatherNextTrader")

def run(scan_only: bool = False, execute: bool = False, max_events: int = 15):
    if execute:
        from daemon import WeatherTradingDaemon
        WeatherTradingDaemon(max_events=max_events).run_cycle(1)
        return
    print("=" * 80)
    print(f"🌦️  POLYMARKET WEATHER ENGINE (Mode: {cfg.MODE.value})")
    print("=" * 80)

    # 1. Initialize Clients
    gamma = GammaClient()
    clob = ClobMarketClient()
    nowcaster = MetarNowcaster()
    
    # Initialize Weather Provider (WeatherNext with Public Fallback)
    wn_provider = WeatherNextProvider()
    if wn_provider.initialized:
        weather_provider = wn_provider
        print(">> Weather Provider: Google DeepMind WeatherNext 3 (Active)")
    else:
        weather_provider = PublicFallbackProvider()
        print(">> Weather Provider: Open-Meteo High-Resolution Ensemble (Live Fallback)")

    # Initialize Broker
    if cfg.MODE == ExecutionMode.LIVE:
        broker = LiveBroker()
    else:
        broker = PaperBroker()

    portfolio = broker.get_portfolio_state()
    print(f">> Portfolio Value: ${portfolio.total_portfolio_value_usdc:,.2f} | Liquid Cash: ${portfolio.cash_usdc:,.2f}")
    print()

    # 2. Monitor Active Positions & Evaluate Early Exits (Strategy B)
    exit_signals = []
    if portfolio.positions:
        print(f">> Active Open Positions ({len(portfolio.positions)}):")
        pos_rows = []
        current_prices = {}
        for tok_id, pos in portfolio.positions.items():
            best_bid, _, mid = clob.get_market_quote(tok_id)
            current_prices[tok_id] = best_bid
            roi = (current_prices[tok_id] - pos.avg_entry_price) / pos.avg_entry_price * 100.0 if pos.avg_entry_price > 0 else 0.0
            pos_rows.append([
                pos.contract_title[:32],
                pos.bracket_label,
                f"{pos.shares:,.0f}",
                f"${pos.avg_entry_price:.3f}",
                f"${current_prices[tok_id]:.3f}",
                f"${pos.shares * current_prices[tok_id]:.2f}",
                f"{'+' if roi >= 0 else ''}{roi:.1f}%"
            ])
        print(tabulate(pos_rows, headers=["Event", "Bracket", "Shares", "Avg Entry", "Current", "Value", "Unrealized ROI"], tablefmt="simple"))
        print()

        # Evaluate potential take-profit or stop-loss exits
        exit_signals = ExitManager.evaluate_position_exits(portfolio, current_prices, {})
        if exit_signals:
            print(f">> ⚡ Detected {len(exit_signals)} Exit Opportunities (Take-Profit / Risk-Reduction):")
            for ex in exit_signals:
                print(f"   • SELL {ex.recommended_shares}x {ex.target_token_id}: {ex.rationale}")

    # 3. Discover Active Weather Events
    print(">> Fetching active Polymarket weather markets...")
    contracts = gamma.fetch_active_weather_events(max_pages=3)
    print(f"   Found {len(contracts)} active weather contracts.")

    if not contracts:
        print("No active weather markets found at this time.")
        return

    all_signals = []

    # 4. Analyze each contract
    for idx, contract in enumerate(contracts[:max_events], 1):
        forecast = weather_provider.get_hourly_forecast(
            station_icao=contract.station_icao,
            lat=contract.lat,
            lon=contract.lon,
            target_date=contract.target_date,
            unit=contract.unit
        )

        if not forecast:
            continue

        # Resolve station microclimate & live METAR nowcasting
        station = resolve_station(contract.station_icao) or resolve_station(contract.city)
        nowcast = nowcaster.fetch_station_nowcast(station, contract.target_date) if station else None

        # Calculate Fair Value Probabilities with Microclimate & METAR Pruning
        contract.brackets = BracketPricer.price_contract_brackets(contract, forecast, nowcast=nowcast)

        # Print Table for contract
        print(f"\n[{idx}] {contract.event_title}")
        print(f"    Oracle: {contract.station_name} ({contract.station_icao.upper()}) | Target: {contract.target_date} ({contract.metric.value})")
        if station:
            print(f"    Station Microclimate: {station.station_type} (Elev: {station.elevation_m:.0f}m, Bias: {station.microclimate_bias_c:+.1f}°C)")
        if nowcast and nowcast.is_today:
            sky_desc = f"{nowcast.cloud_cover} ({'Overcast' if nowcast.is_overcast else 'Clear/Scattered'})"
            today_max_str = f"{nowcast.today_max_c:.1f}°C" if contract.unit.value == "C" else f"{nowcast.today_max_f:.1f}°F"
            latest_str = f"{nowcast.latest_temp_c:.1f}°C" if contract.unit.value == "C" else f"{nowcast.latest_temp_f:.1f}°F"
            print(f"    ⚡ METAR Nowcast: {latest_str} at {nowcast.local_time_str} | Peak Today: {today_max_str} | Sky: {sky_desc}")

        table_data = []
        for b in contract.brackets:
            edge = b.model_prob - b.market_price_yes
            if b.veto_reason:
                indicator = "🚫 VETO (METAR)"
            elif edge >= cfg.MIN_EDGE_THRESHOLD and 0.01 < b.market_price_yes < 0.95:
                indicator = "🟢 BUY"
            else:
                indicator = "  -"
            table_data.append([
                b.label,
                f"{b.market_price_yes*100:5.1f}%",
                f"{b.model_prob*100:5.1f}%",
                f"{'+' if edge > 0 else ''}{edge*100:5.1f}%",
                f"${b.ev:+.2f}",
                indicator
            ])

        print(tabulate(table_data, headers=["Bracket", "Market %", "Model %", "Edge %", "EV/Share", "Signal"], tablefmt="simple"))

        # Generate Signals
        signals = EdgeCalculator.compute_signals(contract, portfolio.cash_usdc)
        all_signals.extend(signals)

    # 5. Risk Filtering & Allocation for Entries
    approved_signals = RiskManager.filter_and_scale_signals(all_signals, portfolio)

    print("\n" + "=" * 80)
    print(f"📊 SUMMARY OF GENERATED TRADING SIGNALS ({len(approved_signals)} Approved)")
    print("=" * 80)

    if not approved_signals:
        print("No mispriced brackets found exceeding the edge hurdle threshold.")
    else:
        sig_rows = []
        for s in approved_signals:
            sig_rows.append([
                s.contract.city,
                s.bracket.label,
                f"{s.market_price*100:.1f}%",
                f"{s.model_prob*100:.1f}%",
                f"+{s.edge*100:.1f}%",
                s.recommended_shares,
                f"${s.recommended_spend_usdc:.2f}"
            ])
        print(tabulate(sig_rows, headers=["City", "Bracket", "Market", "Model", "Edge", "Shares", "Spend"], tablefmt="grid"))

    # 6. Execute if enabled
    signals_to_execute = exit_signals + approved_signals
    if execute and signals_to_execute:
        print(f"\n>> Executing {len(signals_to_execute)} operations in {cfg.MODE.value} mode...")
        results = broker.execute_signals(signals_to_execute)
        print(f">> Executed {len(results)} operations successfully!")

        updated_port = broker.get_portfolio_state()
        print(f">> Updated Cash: ${updated_port.cash_usdc:,.2f} | Open Positions: {len(updated_port.positions)} | Realized PnL: ${updated_port.realized_pnl_usdc:+.2f}")
    elif not execute and approved_signals:
        print("\n>> To execute these trades, pass --execute (or run in continuous paper mode).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket Weather Trading Engine")
    parser.add_argument("--scan-only", action="store_true", help="Only scan and display fair value tables")
    parser.add_argument("--execute", action="store_true", help="Execute trades (Paper or Live)")
    parser.add_argument("--limit", type=int, default=10, help="Max events to evaluate")
    args = parser.parse_args()

    run(scan_only=args.scan_only, execute=args.execute, max_events=args.limit)
