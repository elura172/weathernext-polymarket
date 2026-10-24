"""Exposure limits use persistent city and market identity, including existing cost."""
from collections import defaultdict
from math import isfinite
from models import OrderSide
from config import cfg
from registry.stations import resolve_station


def city_key(city_or_title):
    station = resolve_station(city_or_title)
    return station.city.casefold() if station else None


class RiskManager:
    @staticmethod
    def filter_and_scale_signals(signals, portfolio):
        if not portfolio.risk_data_complete or portfolio.pending_buy_orders:
            return []
        value = portfolio.total_portfolio_value_usdc
        if not isfinite(value) or value <= 0:
            return []
        investable = max(0.0, portfolio.cash_usdc - value * cfg.MIN_CASH_RESERVE)
        cities, markets = defaultdict(float), defaultdict(float)
        for pos in portfolio.positions.values():
            if pos.redeemable:
                continue
            city = city_key(pos.city or pos.contract_title)
            market = pos.condition_id or pos.market_id
            if city is None or not market:
                return []  # Unknown exposure must not silently disappear.
            cities[city] += pos.total_cost_usdc
            markets[market] += pos.total_cost_usdc
        approved = []
        for sig in sorted(signals, key=lambda s: s.edge, reverse=True):
            if sig.side != OrderSide.BUY or not sig.contract or not sig.bracket:
                continue
            city = city_key(sig.contract.city)
            market = sig.bracket.condition_id or sig.bracket.market_id
            if city is None or not market or not isfinite(sig.target_price) or not 0 < sig.target_price < 1:
                continue
            allowed = min(sig.recommended_spend_usdc, cfg.MAX_TRADE_USDC, investable,
                          value * cfg.MAX_CITY_ALLOCATION - cities[city],
                          value * cfg.MAX_CONTRACT_ALLOCATION - markets[market])
            if not isfinite(allowed) or allowed < 1.0:
                continue
            shares = min(sig.recommended_shares, int(allowed / sig.target_price))
            spend = round(shares * sig.target_price, 6)
            if shares <= 0 or spend < 1.0:
                continue
            sig.recommended_shares = shares
            sig.recommended_spend_usdc = spend
            investable -= spend
            cities[city] += spend
            markets[market] += spend
            approved.append(sig)
        return approved
