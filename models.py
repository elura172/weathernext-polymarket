"""
Core data models for Polymarket Weather Intelligence & Trading Engine.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class MetricType(str, Enum):
    T_MAX = "T_MAX"  # Highest / Maximum Temperature
    T_MIN = "T_MIN"  # Lowest / Minimum Temperature


class UnitType(str, Enum):
    FAHRENHEIT = "F"
    CELSIUS = "C"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass
class Bracket:
    market_id: str
    condition_id: str
    token_id_yes: str
    token_id_no: str
    label: str               # e.g., "83°F or below", "84°F", "87°F or higher"
    min_temp: float          # Lower bound
    max_temp: float          # Upper bound
    market_price_yes: float  # Current best price on Polymarket (0.0 to 1.0)
    market_price_no: float
    model_prob: float = 0.0  # Fair value probability from WeatherNext 3
    ev: float = 0.0          # Expected value (EV) per share
    kelly_size: float = 0.0  # Recommended allocation fraction
    veto_reason: Optional[str] = None


@dataclass
class WeatherContract:
    event_id: str
    event_title: str
    event_slug: str
    city: str
    station_icao: str
    station_name: str
    lat: float
    lon: float
    timezone: str
    metric: MetricType
    unit: UnitType
    target_date: str          # YYYY-MM-DD
    resolution_source_url: str
    precision: float          # 1.0 for whole degrees, 0.1 for decimals
    brackets: List[Bracket] = field(default_factory=list)
    raw_description: str = ""


@dataclass
class HourlyForecast:
    station_icao: str
    target_date: str
    timestamps: List[datetime]
    temperatures: List[float]  # in the contract's unit
    t_max: float
    t_min: float
    ensemble_std: float        # Uncertainty spread (std dev in °F or °C)
    source_model: str          # "WeatherNext3", "OpenMeteo-ECMWF", etc.


@dataclass
class TradeSignal:
    contract: WeatherContract
    bracket: Bracket
    side: OrderSide
    target_token_id: str
    target_price: float
    model_prob: float
    market_price: float
    edge: float                # model_prob - market_price
    ev_per_share: float
    recommended_shares: int
    recommended_spend_usdc: float
    rationale: str


@dataclass
class Position:
    token_id: str
    market_id: str
    condition_id: str
    contract_title: str
    bracket_label: str
    shares: float
    avg_entry_price: float
    total_cost_usdc: float
    current_market_price: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    redeemable: bool = False
    city: str = ""


@dataclass
class PortfolioState:
    cash_usdc: float
    positions: Dict[str, Position] = field(default_factory=dict)
    total_portfolio_value_usdc: float = 0.0
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    history: List[Dict[str, Any]] = field(default_factory=list)
    risk_data_complete: bool = True
    pending_buy_orders: bool = False
