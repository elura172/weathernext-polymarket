"""
Gamma API Client for Polymarket Event & Market Discovery.
Fetches active weather contracts with pagination and volume sorting.
"""
import requests
import json
import logging
from typing import List, Dict, Any, Optional
from config import cfg
from models import WeatherContract
from polymarket.parser import parse_weather_event

logger = logging.getLogger(__name__)

class GammaClient:
    def __init__(self, base_url: str = cfg.GAMMA_API_BASE):
        self.base_url = base_url.rstrip("/")

    def fetch_active_weather_events(self, max_pages: int = 5, page_size: int = 100) -> List[WeatherContract]:
        """Discover and parse all active weather contracts across Polymarket."""
        contracts: List[WeatherContract] = []
        seen_ids = set()

        for page in range(max_pages):
            offset = page * page_size
            url = f"{self.base_url}/events"
            params = {
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
                "limit": page_size,
                "offset": offset
            }
            try:
                resp = requests.get(url, params=params, timeout=12)
                resp.raise_for_status()
                events = resp.json()
                if not events or not isinstance(events, list):
                    break

                for ev in events:
                    ev_id = str(ev.get("id"))
                    if ev_id in seen_ids:
                        continue
                    seen_ids.add(ev_id)

                    title = ev.get("title", "").lower()
                    if any(k in title for k in ["temperature in", "highest temp", "lowest temp", "temperature on"]):
                        contract = parse_weather_event(ev)
                        if contract and contract.brackets:
                            contracts.append(contract)

            except Exception as e:
                logger.error(f"Error fetching page {page} from Gamma API: {e}")
                break

        return contracts

    def get_resolved_token_outcome(self, market_id: str, token_id: str):
        """Settle paper holdings only from final exchange outcomes, never forecasts."""
        try:
            resp = requests.get(f"{self.base_url}/markets/{market_id}", timeout=12)
            resp.raise_for_status()
            market = resp.json()
            if market.get("closed") is not True or market.get("umaResolutionStatus") != "resolved":
                return None
            tokens = market.get("clobTokenIds", [])
            prices = market.get("outcomePrices", [])
            tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
            prices = json.loads(prices) if isinstance(prices, str) else prices
            values = [float(price) for price in prices]
            if len(tokens) != len(values) or len(values) != 2 or sorted(values) != [0.0, 1.0]:
                return None
            return values[tokens.index(token_id)] == 1.0
        except Exception as exc:
            logger.warning("Resolution unavailable for %s: %s", market_id, exc)
            return None
