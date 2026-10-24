"""
Unit tests for PaperBroker ledger and execution.
"""
import os
from types import SimpleNamespace
from execution.paper_broker import PaperBroker
from models import TradeSignal, WeatherContract, Bracket, MetricType, UnitType, OrderSide

def test_paper_broker_flow(tmp_path):
    ledger_file = str(tmp_path / "test_ledger.json")
    broker = PaperBroker(ledger_path=ledger_file, initial_cash=500.0, market_client=SimpleNamespace(get_order_book=lambda token: {"bids": [{"price": .29, "size": 100}], "asks": [{"price": .30, "size": 100}]}))
    
    port = broker.get_portfolio_state()
    assert port.cash_usdc == 500.0
    assert len(port.positions) == 0

    contract = WeatherContract(
        event_id="e1",
        event_title="Highest temperature in Toronto",
        event_slug="test",
        city="Toronto",
        station_icao="cyyz",
        station_name="Pearson",
        lat=43.67,
        lon=-79.62,
        timezone="America/Toronto",
        metric=MetricType.T_MAX,
        unit=UnitType.CELSIUS,
        target_date="2026-09-04",
        resolution_source_url="",
        precision=1.0
    )
    bracket = Bracket("m1", "c1", "tok_yes", "tok_no", "25°C", 24.5, 25.5, 0.30, 0.70, model_prob=0.55)
    sig = TradeSignal(
        contract=contract,
        bracket=bracket,
        side=OrderSide.BUY,
        target_token_id="tok_yes",
        target_price=0.30,
        model_prob=0.55,
        market_price=0.30,
        edge=0.25,
        ev_per_share=0.25,
        recommended_shares=10,
        recommended_spend_usdc=3.0,
        rationale="Test edge"
    )

    executed = broker.execute_signals([sig])
    assert len(executed) == 1
    
    updated_port = broker.get_portfolio_state()
    assert updated_port.cash_usdc < 500.0
    assert "tok_yes" in updated_port.positions
    assert updated_port.positions["tok_yes"].shares == 10
