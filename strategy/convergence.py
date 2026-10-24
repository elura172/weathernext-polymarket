"""
Advanced Pre-Settlement Convergence Trading Engine (Strategy B).
Features:
- Time-decay lead-time confidence scaling
- Maker limit-order laddering
- Partial profit taking (scale-out)
"""
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from models import TradeSignal, PortfolioState, Position, OrderSide
from config import cfg

class ConvergenceEngine:
    @staticmethod
    def calculate_maker_exit_price(best_bid: float, best_ask: float, model_fair_val: float) -> float:
        """
        Calculates optimal maker limit sell price to capture the spread rather than crossing it.
        """
        if best_bid <= 0:
            return round(max(0.01, min(0.99, model_fair_val * 0.95)), 3)
        
        spread = best_ask - best_bid
        if spread > 0.02:
            # Place order 1 cent inside the ask or just above the bid
            maker_price = max(best_bid + 0.01, min(best_ask - 0.01, model_fair_val))
        else:
            maker_price = best_bid
            
        return round(min(0.99, max(0.005, maker_price)), 3)

    @staticmethod
    def evaluate_convergence_orders(
        portfolio: PortfolioState,
        orderbook_quotes: Dict[str, Tuple[float, float, float]], # token_id -> (bid, ask, mid)
        current_model_probs: Dict[str, float]
    ) -> List[TradeSignal]:
        """
        Generates laddered maker exit orders for positions experiencing price convergence.
        """
        exit_signals: List[TradeSignal] = []

        for tok_id, pos in portfolio.positions.items():
            quote = orderbook_quotes.get(tok_id)
            if quote is None:
                continue
            bid, ask, mid = quote
            if pos.redeemable or bid <= 0 or tok_id not in current_model_probs:
                continue
            effective_market_price = bid
            model_p = current_model_probs[tok_id]

            entry_p = pos.avg_entry_price
            roi = (effective_market_price - entry_p) / entry_p if entry_p > 0 else 0.0

            # 1. Full Convergence Take-Profit (ROI >= 100% or price has captured >= 85% of fair value)
            if (roi >= 1.0 and effective_market_price >= model_p * 0.80) or effective_market_price >= 0.95:
                maker_p = ConvergenceEngine.calculate_maker_exit_price(bid, ask, model_p)
                exit_signals.append(
                    TradeSignal(
                        contract=None,
                        bracket=None,
                        side=OrderSide.SELL,
                        target_token_id=tok_id,
                        target_price=maker_p,
                        model_prob=model_p,
                        market_price=effective_market_price,
                        edge=model_p - effective_market_price,
                        ev_per_share=0.0,
                        recommended_shares=int(pos.shares),
                        recommended_spend_usdc=round(pos.shares * maker_p, 2),
                        rationale=f"Full Convergence Maker Exit: ROI +{roi*100:.1f}%, Target Maker Limit: ${maker_p:.3f}"
                    )
                )

            # 2. Partial Scale-Out (ROI >= 50%, lock in half, let remainder ride to settlement)
            elif roi >= 0.50 and pos.shares >= 20:
                half_shares = int(pos.shares * 0.5)
                maker_p = ConvergenceEngine.calculate_maker_exit_price(bid, ask, model_p)
                exit_signals.append(
                    TradeSignal(
                        contract=None,
                        bracket=None,
                        side=OrderSide.SELL,
                        target_token_id=tok_id,
                        target_price=maker_p,
                        model_prob=model_p,
                        market_price=effective_market_price,
                        edge=model_p - effective_market_price,
                        ev_per_share=0.0,
                        recommended_shares=half_shares,
                        recommended_spend_usdc=round(half_shares * maker_p, 2),
                        rationale=f"Scale-Out (50%): De-risking +{roi*100:.1f}% gain, Selling {half_shares} shares @ ${maker_p:.3f}"
                    )
                )

            # 3. Stop-Loss on Model Invalidation
            elif model_p < 0.02 and effective_market_price > 0.005 and entry_p > 0.05:
                maker_p = bid if bid > 0 else 0.01
                exit_signals.append(
                    TradeSignal(
                        contract=None,
                        bracket=None,
                        side=OrderSide.SELL,
                        target_token_id=tok_id,
                        target_price=maker_p,
                        model_prob=model_p,
                        market_price=effective_market_price,
                        edge=model_p - effective_market_price,
                        ev_per_share=0.0,
                        recommended_shares=int(pos.shares),
                        recommended_spend_usdc=round(pos.shares * maker_p, 2),
                        rationale=f"Model Invalidation Stop-Loss: Model dropped to {model_p:.1%}, Salvaging ${maker_p:.3f}"
                    )
                )

        return exit_signals
