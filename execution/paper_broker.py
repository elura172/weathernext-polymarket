"""
Paper Trading Broker.
Maintains persistent JSON ledger, simulates order execution with spread & slippage,
and tracks real-time unrealized/realized PnL.
"""
import json
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from models import TradeSignal, PortfolioState, Position
from execution.base_broker import BaseBroker
from config import cfg
from polymarket.clob_client import ClobMarketClient
from registry.stations import resolve_station

logger = logging.getLogger(__name__)

class PaperBroker(BaseBroker):
    def __init__(self, ledger_path: str = cfg.PAPER_LEDGER_PATH, initial_cash: float = cfg.INITIAL_PAPER_CASH, market_client=None):
        self.ledger_path = ledger_path
        self.initial_cash = initial_cash
        self.market_client = market_client or ClobMarketClient()
        self._load_or_create_ledger()

    def _load_or_create_ledger(self):
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        if not os.path.exists(self.ledger_path):
            self.state = {
                "schema_version": 2,
                "execution_model": "crossed-book-depth-only; excludes fees and queue fills",
                "cash_usdc": self.initial_cash,
                "realized_pnl_usdc": 0.0,
                "positions": {},
                "trades": []
            }
            self._save()
        else:
            with open(self.ledger_path, "r") as f:
                self.state = json.load(f)
            if self.state.get("schema_version") != 2:
                raise ValueError("Legacy paper ledger is invalid for execution; use a fresh v2 ledger")

    def _save(self):
        with open(self.ledger_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def get_portfolio_state(self) -> PortfolioState:
        cash = float(self.state.get("cash_usdc", self.initial_cash))
        realized_pnl = float(self.state.get("realized_pnl_usdc", 0.0))
        positions: Dict[str, Position] = {}
        total_pos_val = 0.0
        unrealized_pnl = 0.0

        for tok_id, pos_dict in self.state.get("positions", {}).items():
            pos = Position(
                token_id=tok_id,
                market_id=pos_dict["market_id"],
                condition_id=pos_dict["condition_id"],
                contract_title=pos_dict["contract_title"],
                bracket_label=pos_dict["bracket_label"],
                shares=float(pos_dict["shares"]),
                avg_entry_price=float(pos_dict["avg_entry_price"]),
                total_cost_usdc=float(pos_dict["total_cost_usdc"]),
                city=pos_dict.get("city", ""),
                current_market_price=float(pos_dict.get("current_market_price", 0.0))
            )
            val = pos.shares * pos.current_market_price
            pos.unrealized_pnl_usdc = val - pos.total_cost_usdc
            total_pos_val += val
            unrealized_pnl += pos.unrealized_pnl_usdc
            positions[tok_id] = pos

        total_val = cash + total_pos_val
        return PortfolioState(
            cash_usdc=cash,
            positions=positions,
            total_portfolio_value_usdc=total_val,
            realized_pnl_usdc=realized_pnl,
            unrealized_pnl_usdc=unrealized_pnl,
            history=self.state.get("trades", [])
        )

    def mark_to_market(self):
        """Conservative bid-depth liquidation marks, never ask or maker targets."""
        for token, pos in self.state["positions"].items():
            book = self.market_client.get_order_book(token)
            remaining, value = pos["shares"], 0.0
            for level in (book or {}).get("bids", []):
                size = min(remaining, level["size"])
                value += size * level["price"]
                remaining -= size
                if remaining <= 0:
                    break
            pos["current_market_price"] = value / pos["shares"] if pos["shares"] else 0.0
            pos["quote_available"] = book is not None
        self._save()

    def execute_signals(self, signals):
        # No queue-fill invention: non-crossing limits stay unfilled. A snapshot's
        # liquidity is consumed at most once per batch, including partial fills.
        executed, books = [], {}
        for sig in signals:
            token = sig.target_token_id
            if token not in books:
                books[token] = self.market_client.get_order_book(token)
            book = books[token]
            if book is None:
                continue
            selling = sig.side.value == "SELL"
            pos = self.state["positions"].get(token)
            if selling and not pos:
                continue
            remaining = min(float(sig.recommended_shares), pos["shares"]) if selling else float(sig.recommended_shares)
            budget = min(self.state["cash_usdc"], sig.recommended_spend_usdc, cfg.MAX_TRADE_USDC)
            filled, amount = 0.0, 0.0
            for level in book["bids" if selling else "asks"]:
                price = level["price"]
                if (selling and price < sig.target_price) or (not selling and price > sig.target_price):
                    break
                size = min(remaining, level["size"])
                if not selling:
                    size = min(size, max(0.0, budget - amount) / price)
                if size <= 0:
                    break
                filled += size
                amount += size * price
                remaining -= size
                level["size"] -= size
                if remaining <= 1e-9:
                    break
            if filled <= 0:
                continue
            fill_price = amount / filled
            record = {"timestamp": datetime.now(timezone.utc).isoformat(),
                      "token_id": token, "side": sig.side.value, "shares": filled,
                      "fill_price": fill_price, "spend_usdc": -amount if selling else amount,
                      "status": "FILLED" if remaining <= 1e-9 else "PARTIALLY_FILLED",
                      "rationale": sig.rationale}
            if selling:
                cost = pos["total_cost_usdc"] * filled / pos["shares"]
                profit = amount - cost
                self.state["cash_usdc"] += amount
                self.state["realized_pnl_usdc"] += profit
                record.update(event_title=pos["contract_title"], bracket=pos["bracket_label"], realized_profit_usdc=profit)
                pos["shares"] -= filled
                pos["total_cost_usdc"] -= cost
                if pos["shares"] <= 1e-9:
                    del self.state["positions"][token]
            else:
                self.state["cash_usdc"] -= amount
                record.update(event_title=sig.contract.event_title, bracket=sig.bracket.label,
                              model_prob=sig.model_prob, edge=sig.edge)
                if not pos:
                    pos = {"market_id": sig.bracket.market_id, "condition_id": sig.bracket.condition_id,
                           "contract_title": sig.contract.event_title, "bracket_label": sig.bracket.label,
                           "city": sig.contract.city, "shares": 0.0, "total_cost_usdc": 0.0}
                    self.state["positions"][token] = pos
                pos["shares"] += filled
                pos["total_cost_usdc"] += amount
                pos["avg_entry_price"] = pos["total_cost_usdc"] / pos["shares"]
                pos["current_market_price"] = book["bids"][0]["price"] if book["bids"] else 0.0
            self.state["trades"].append(record)
            executed.append(record)
        self._save()
        return executed

    def resolve_position(
        self,
        token_id: str,
        actual_recorded_temp: float,
        min_temp: float,
        max_temp: float,
        is_winner: Optional[bool] = None
    ) -> Optional[dict]:
        """
        Settles a completed weather contract.
        If is_winner is provided, uses that. Otherwise checks min_temp <= actual <= max_temp (or opposite if bracket is 'No').
        If winner, token pays $1.00 each. Otherwise expires worthless at $0.00.
        """
        pos = self.state["positions"].get(token_id)
        if not pos:
            return None

        if is_winner is None:
            in_range = min_temp <= actual_recorded_temp <= max_temp
            if pos.get("bracket_label", "").strip().lower() == "no":
                is_winner = not in_range
            else:
                is_winner = in_range

        shares = pos["shares"]
        cost = pos["total_cost_usdc"]

        if is_winner:
            payout = round(shares * 1.0, 2)
            profit = round(payout - cost, 2)
            self.state["cash_usdc"] += payout
            self.state["realized_pnl_usdc"] = round(self.state.get("realized_pnl_usdc", 0.0) + profit, 2)
            resolution_status = "WINNER"
        else:
            payout = 0.0
            profit = -cost
            self.state["realized_pnl_usdc"] = round(self.state.get("realized_pnl_usdc", 0.0) + profit, 2)
            resolution_status = "EXPIRED_LOSS"

        del self.state["positions"][token_id]

        res_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_title": pos.get("contract_title"),
            "bracket": pos.get("bracket_label"),
            "resolution": resolution_status,
            "actual_recorded_temp": actual_recorded_temp,
            "shares": shares,
            "payout_usdc": payout,
            "realized_profit_usdc": profit
        }
        self.state["trades"].append(res_record)
        self._save()
        logger.info(f"SETTLEMENT: {pos.get('contract_title')} - {pos.get('bracket_label')}: {resolution_status} (Payout: ${payout:.2f}, Profit: ${profit:+.2f})")
        return res_record
