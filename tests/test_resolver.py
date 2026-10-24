"""
Unit tests for Oracle Settlement and Position Resolution.
"""
from execution.paper_broker import PaperBroker

def test_settlement_winner_payout(tmp_path):
    ledger_file = str(tmp_path / "test_settle_win.json")
    broker = PaperBroker(ledger_path=ledger_file, initial_cash=100.0)
    
    # Manually inject open position
    broker.state["positions"]["tok_win"] = {
        "market_id": "m1",
        "condition_id": "c1",
        "contract_title": "Highest temperature in Dallas on Sept 3",
        "bracket_label": "92-93°F",
        "shares": 500,
        "avg_entry_price": 0.20,
        "total_cost_usdc": 100.0,
        "current_market_price": 0.20
    }
    broker.state["cash_usdc"] = 0.0
    broker._save()

    # Actual recorded was 92°F -> Winner!
    res = broker.resolve_position("tok_win", actual_recorded_temp=92.0, min_temp=91.5, max_temp=93.5)
    assert res["resolution"] == "WINNER"
    assert res["payout_usdc"] == 500.0
    assert res["realized_profit_usdc"] == 400.0
    assert broker.state["cash_usdc"] == 500.0
    assert broker.state["realized_pnl_usdc"] == 400.0
    assert "tok_win" not in broker.state["positions"]

def test_settlement_expired_loss(tmp_path):
    ledger_file = str(tmp_path / "test_settle_loss.json")
    broker = PaperBroker(ledger_path=ledger_file, initial_cash=100.0)
    
    broker.state["positions"]["tok_loss"] = {
        "market_id": "m2",
        "condition_id": "c2",
        "contract_title": "Highest temperature in Dallas on Sept 3",
        "bracket_label": "88-89°F",
        "shares": 500,
        "avg_entry_price": 0.10,
        "total_cost_usdc": 50.0,
        "current_market_price": 0.10
    }
    broker.state["cash_usdc"] = 50.0
    broker._save()

    # Actual recorded was 92°F -> Loser!
    res = broker.resolve_position("tok_loss", actual_recorded_temp=92.0, min_temp=87.5, max_temp=89.5)
    assert res["resolution"] == "EXPIRED_LOSS"
    assert res["payout_usdc"] == 0.0
    assert res["realized_profit_usdc"] == -50.0
    assert broker.state["cash_usdc"] == 50.0
    assert broker.state["realized_pnl_usdc"] == -50.0
    assert "tok_loss" not in broker.state["positions"]

def test_resolve_contract_outcome_with_mock(monkeypatch):
    from execution.resolver import OracleResolver

    # Mock fetch_station_recorded_extreme to return 91.0
    monkeypatch.setattr(
        OracleResolver,
        "fetch_station_recorded_extreme",
        lambda station_icao, lat, lon, obs_date, metric, unit: 91.0
    )

    # 1. Yes on 90-91°F when actual is 91 -> Winner
    is_win, rec, bounds = OracleResolver.resolve_contract_outcome(
        "Will the highest temperature in Denver be between 90-91°F on September 3?",
        bracket_label="Yes",
        target_date="2026-09-03"
    )
    assert is_win is True
    assert rec == 91.0
    assert bounds == (89.5, 91.5)

    # 2. Bracket label range 88-89°F when actual is 91 -> Loser
    is_win_loss, rec_loss, bounds_loss = OracleResolver.resolve_contract_outcome(
        "Highest temperature in Denver on September 3?",
        bracket_label="88-89°F",
        target_date="2026-09-03"
    )
    assert is_win_loss is False
    assert rec_loss == 91.0

    # 3. No on 88-89°F when actual is 91 -> Winner
    is_win_no, rec_no, bounds_no = OracleResolver.resolve_contract_outcome(
        "Will the highest temperature in Denver be between 88-89°F on September 3?",
        bracket_label="No",
        target_date="2026-09-03"
    )
    assert is_win_no is True
    assert rec_no == 91.0
