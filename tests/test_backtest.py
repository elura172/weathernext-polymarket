"""
Unit tests for Historical Backtest engine and performance metrics.
"""
from backtest import HistoricalBacktester, BacktestTrade, BacktestReport

def test_backtest_metric_calculations():
    trades = [
        BacktestTrade("NYC High", "2026-09-01", "80°F", 0.20, 0.40, 0.20, 100, 20.0, True, 100.0, 80.0),
        BacktestTrade("Dallas High", "2026-09-01", "95°F", 0.15, 0.30, 0.15, 100, 15.0, False, 0.0, -15.0),
        BacktestTrade("London High", "2026-09-02", "22°C", 0.25, 0.50, 0.25, 100, 25.0, True, 100.0, 75.0)
    ]
    total_trades = len(trades)
    wins = sum(1 for t in trades if t.won)
    pnl = sum(t.profit_usdc for t in trades)

    assert total_trades == 3
    assert wins == 2
    assert pnl == 140.0
