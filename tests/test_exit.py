"""
Unit tests for Convergence Exit & Take-Profit Engine.
"""
from strategy.exit import ExitManager
from models import PortfolioState, Position, OrderSide

def test_convergence_take_profit():
    pos = Position(
        token_id="tok1",
        market_id="m1",
        condition_id="c1",
        contract_title="Highest temperature in London",
        bracket_label="22°C",
        shares=1000,
        avg_entry_price=0.10,
        total_cost_usdc=100.0,
        current_market_price=0.25
    )
    port = PortfolioState(
        cash_usdc=500.0,
        positions={"tok1": pos},
        total_portfolio_value_usdc=750.0
    )

    # Market price has moved to $0.25 (150% ROI), model is at 0.28
    current_prices = {"tok1": 0.25}
    current_models = {"tok1": 0.28}

    exits = ExitManager.evaluate_position_exits(port, current_prices, current_models)
    assert len(exits) == 1
    assert exits[0].side == OrderSide.SELL
    assert exits[0].recommended_shares == 1000
    assert "Take-Profit" in exits[0].rationale

def test_stop_loss_on_model_collapse():
    pos = Position(
        token_id="tok2",
        market_id="m2",
        condition_id="c2",
        contract_title="Highest temperature in Dallas",
        bracket_label="95°F",
        shares=500,
        avg_entry_price=0.20,
        total_cost_usdc=100.0,
        current_market_price=0.05
    )
    port = PortfolioState(
        cash_usdc=500.0,
        positions={"tok2": pos},
        total_portfolio_value_usdc=525.0
    )

    # WeatherNext 3 updated with cold front; prob collapsed to 0.5%
    current_prices = {"tok2": 0.04}
    current_models = {"tok2": 0.005}

    exits = ExitManager.evaluate_position_exits(port, current_prices, current_models)
    assert len(exits) == 1
    assert exits[0].side == OrderSide.SELL
    assert "Stop-Loss" in exits[0].rationale
