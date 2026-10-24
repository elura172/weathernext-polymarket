"""
Edge & Expected Value (EV) calculation, along with Fractional Kelly position sizing.
"""
from typing import List, Optional
from models import WeatherContract, Bracket, TradeSignal, OrderSide
from config import cfg

class EdgeCalculator:
    @staticmethod
    def compute_signals(contract: WeatherContract, portfolio_cash: float) -> List[TradeSignal]:
        """
        Evaluates brackets for positive Expected Value (EV) and generates trade signals.
        """
        signals: List[TradeSignal] = []

        for b in contract.brackets:
            # Skip if vetoed by METAR nowcaster
            if getattr(b, "veto_reason", None):
                continue

            # We evaluate buying YES on underpriced outcomes
            market_p = b.market_price_yes
            model_p = b.model_prob

            edge = model_p - market_p
            b.ev = edge # EV per share = model_p * (1 - price) - (1 - model_p) * price = model_p - price

            # Filter for positive edge above hurdle
            if edge >= max(cfg.MIN_EDGE_THRESHOLD, cfg.MIN_EV_THRESHOLD) and market_p > 0.01 and market_p < 0.95:
                # Kelly formula: f* = (p*b - q) / b where b = (1-p_m)/p_m
                # Simplifies to: f* = (p_model - p_market) / (1 - p_market)
                odds = (1.0 - market_p)
                raw_kelly = edge / odds if odds > 0 else 0.0
                kelly_frac = max(0.0, raw_kelly * cfg.KELLY_FRACTION)

                # Cap single contract allocation
                alloc_frac = min(kelly_frac, cfg.MAX_CONTRACT_ALLOCATION)
                target_spend = portfolio_cash * alloc_frac

                if target_spend >= 1.0: # Minimum $1 order
                    shares = int(target_spend / market_p)
                    if shares > 0:
                        b.kelly_size = alloc_frac
                        signals.append(
                            TradeSignal(
                                contract=contract,
                                bracket=b,
                                side=OrderSide.BUY,
                                target_token_id=b.token_id_yes,
                                target_price=market_p,
                                model_prob=model_p,
                                market_price=market_p,
                                edge=edge,
                                ev_per_share=edge,
                                recommended_shares=shares,
                                recommended_spend_usdc=round(shares * market_p, 2),
                                rationale=(
                                    f"Fair value {model_p:.1%} vs Market {market_p:.1%} "
                                    f"(Edge: +{edge*100:.1f}%, EV: +${edge:.2f}/share)"
                                )
                            )
                        )

        return signals
