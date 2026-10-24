"""
Unit tests for Probabilistic Pricing & Kelly edge calculation.
"""
from models import WeatherContract, Bracket, HourlyForecast, MetricType, UnitType
from strategy.pricer import BracketPricer
from strategy.edge import EdgeCalculator
from datetime import datetime, timezone

def test_bracket_pricer_sum_to_one():
    contract = WeatherContract(
        event_id="e1",
        event_title="Highest temperature in Chicago",
        event_slug="highest-temp-chicago",
        city="Chicago",
        station_icao="kord",
        station_name="O'Hare",
        lat=41.97,
        lon=-87.90,
        timezone="America/Chicago",
        metric=MetricType.T_MAX,
        unit=UnitType.FAHRENHEIT,
        target_date="2026-09-04",
        resolution_source_url="",
        precision=1.0,
        brackets=[
            Bracket("1", "c1", "t1", "t2", "75°F or below", float("-inf"), 75.5, 0.1, 0.9),
            Bracket("2", "c2", "t3", "t4", "76°F", 75.5, 76.5, 0.2, 0.8),
            Bracket("3", "c3", "t5", "t6", "77°F", 76.5, 77.5, 0.4, 0.6),
            Bracket("4", "c4", "t7", "t8", "78°F or higher", 77.5, float("inf"), 0.3, 0.7),
        ]
    )
    forecast = HourlyForecast(
        station_icao="kord",
        target_date="2026-09-04",
        timestamps=[datetime.now(timezone.utc)],
        temperatures=[76.0],
        t_max=76.2,
        t_min=62.0,
        ensemble_std=1.5,
        source_model="Test"
    )
    priced = BracketPricer.price_contract_brackets(contract, forecast)
    total_p = sum(b.model_prob for b in priced)
    assert abs(total_p - 1.0) < 1e-4

def test_edge_calculation():
    contract = WeatherContract(
        event_id="e1",
        event_title="Highest temperature in Dallas",
        event_slug="test",
        city="Dallas",
        station_icao="kdal",
        station_name="Dallas",
        lat=32.84,
        lon=-96.85,
        timezone="America/Chicago",
        metric=MetricType.T_MAX,
        unit=UnitType.FAHRENHEIT,
        target_date="2026-09-04",
        resolution_source_url="",
        precision=1.0,
        brackets=[
            Bracket("1", "c1", "t1", "t2", "85°F", 84.5, 85.5, 0.20, 0.80, model_prob=0.45)
        ]
    )
    signals = EdgeCalculator.compute_signals(contract, portfolio_cash=1000.0)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.edge == 0.25
    assert sig.recommended_spend_usdc > 0
