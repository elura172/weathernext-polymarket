"""
Pre-Settlement Convergence Trading & Risk Exit Engine (Strategy B).
Monitors marked-to-market prices and generates SELL signals:
1. Convergence Take-Profit: Lock in profits early when market catches up to model.
2. Adverse Update Stop-Loss: Cut positions early if an updated weather run invalidates the edge.
"""
from typing import List, Dict, Optional
from models import TradeSignal, PortfolioState, Position, OrderSide
from config import cfg

class ExitManager:
    @staticmethod
    def evaluate_position_exits(
        portfolio: PortfolioState,
        current_market_prices: Dict[str, float],
        current_model_probs: Dict[str, float]
    ) -> List[TradeSignal]:
        """
        Evaluates active positions for early take-profit or stop-loss.
        """
        exit_signals: List[TradeSignal] = []

        for tok_id, pos in portfolio.positions.items():
            market_p = current_market_prices.get(tok_id, 0.0)
            if pos.redeemable or market_p <= 0 or tok_id not in current_model_probs:
                continue
            model_p = current_model_probs[tok_id]

            roi = (market_p - pos.avg_entry_price) / pos.avg_entry_price if pos.avg_entry_price > 0 else 0.0

            # Condition 1: Convergence Take-Profit (e.g., gain >= 50% AND market price reached fair value)
            if roi >= 0.50 and market_p >= (model_p * 0.85):
                exit_signals.append(
                    TradeSignal(
                        contract=None,
                        bracket=None,
                        side=OrderSide.SELL,
                        target_token_id=tok_id,
                        target_price=market_p,
                        model_prob=model_p,
                        market_price=market_p,
                        edge=model_p - market_p,
                        ev_per_share=0.0,
                        recommended_shares=int(pos.shares),
                        recommended_spend_usdc=round(pos.shares * market_p, 2),
                        rationale=f"Convergence Take-Profit: ROI +{roi*100:.1f}%, Market ${market_p:.3f} reached model fair value ${model_p:.3f}"
                    )
                )
            # Condition 2: Adverse Weather Run Stop-Loss (model probability collapsed below 2%)
            elif model_p < 0.02 and market_p > 0.005 and pos.avg_entry_price > 0.05:
                exit_signals.append(
                    TradeSignal(
                        contract=None,
                        bracket=None,
                        side=OrderSide.SELL,
                        target_token_id=tok_id,
                        target_price=market_p,
                        model_prob=model_p,
                        market_price=market_p,
                        edge=model_p - market_p,
                        ev_per_share=0.0,
                        recommended_shares=int(pos.shares),
                        recommended_spend_usdc=round(pos.shares * market_p, 2),
                        rationale=f"Adverse Forecast Stop-Loss: Model probability dropped to {model_p:.1%}, salvaging ${market_p:.3f}/share"
                    )
                )

        return exit_signals
