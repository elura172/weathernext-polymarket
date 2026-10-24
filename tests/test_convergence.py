"""
Unit tests for Advanced Convergence Trading & Maker Laddering.
"""
from strategy.convergence import ConvergenceEngine
from models import PortfolioState, Position, OrderSide

def test_maker_limit_price_calculation():
    # Inside wide spread: bid=0.20, ask=0.30, fair=0.28
    maker_p = ConvergenceEngine.calculate_maker_exit_price(best_bid=0.20, best_ask=0.30, model_fair_val=0.28)
    assert 0.20 < maker_p <= 0.29

    # Narrow spread: bid=0.24, ask=0.25 -> takes bid
    maker_narrow = ConvergenceEngine.calculate_maker_exit_price(best_bid=0.24, best_ask=0.25, model_fair_val=0.28)
    assert maker_narrow == 0.24

def test_scale_out_50_percent():
    pos = Position(
        token_id="tok_scale",
        market_id="m1",
        condition_id="c1",
        contract_title="Highest temperature in Miami",
        bracket_label="88-89°F",
        shares=100,
        avg_entry_price=0.20,
        total_cost_usdc=20.0,
        current_market_price=0.32 # +60% ROI
    )
    port = PortfolioState(
        cash_usdc=500.0,
        positions={"tok_scale": pos},
        total_portfolio_value_usdc=532.0
    )
    quotes = {"tok_scale": (0.31, 0.33, 0.32)}
    models = {"tok_scale": 0.40}

    exits = ConvergenceEngine.evaluate_convergence_orders(port, quotes, models)
    assert len(exits) == 1
    sig = exits[0]
    assert sig.side == OrderSide.SELL
    assert sig.recommended_shares == 50 # 50% partial take-profit
    assert "Scale-Out (50%)" in sig.rationale
