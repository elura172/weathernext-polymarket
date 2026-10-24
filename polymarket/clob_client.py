"""
CLOB Client for Polymarket Order Book Queries & Live Order Execution.
"""
import requests
import math
import logging
from typing import Optional, Dict, Any, Tuple
from config import cfg

logger = logging.getLogger(__name__)

class ClobMarketClient:
    def __init__(self, base_url: str = cfg.CLOB_API_BASE):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if cfg.PROXY_HTTP:
            self.session.proxies = {
                "http": cfg.PROXY_HTTP,
                "https": cfg.PROXY_HTTP,
            }

    def get_order_book(self, token_id: str) -> Optional[dict]:
        """Validated depth, sorted by executable price; None means unavailable."""
        if not token_id:
            return None
        try:
            resp = self.session.get(f"{self.base_url}/book", params={"token_id": token_id}, timeout=5)
            resp.raise_for_status()
            raw = resp.json()
            result = {}
            for side in ("bids", "asks"):
                levels = []
                for level in raw.get(side, []):
                    price, size = float(level["price"]), float(level["size"])
                    if not (math.isfinite(price) and math.isfinite(size) and 0 < price < 1 and size > 0):
                        raise ValueError("Invalid book level")
                    levels.append({"price": price, "size": size})
                result[side] = sorted(levels, key=lambda level: level["price"], reverse=side == "bids")
            if result["bids"] and result["asks"] and result["bids"][0]["price"] > result["asks"][0]["price"]:
                raise ValueError("Crossed book")
            return result
        except Exception as exc:
            logger.warning("Book unavailable for %s: %s", token_id, exc)
            return None

    def get_market_quote(self, token_id: str) -> Tuple[float, float, float]:
        book = self.get_order_book(token_id)
        if book is None:
            return 0.0, 1.0, 0.0
        bid = book["bids"][0]["price"] if book["bids"] else 0.0
        ask = book["asks"][0]["price"] if book["asks"] else 1.0
        # An ask alone is not evidence of liquidation value.
        mid = (bid + ask) / 2 if book["bids"] and book["asks"] else 0.0
        return bid, ask, mid

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Fetch midpoint price directly."""
        if not token_id:
            return None
        url = f"{self.base_url}/midpoint"
        try:
            resp = self.session.get(url, params={"token_id": token_id}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return float(data.get("mid", 0.0))
        except Exception:
            pass
        return None
