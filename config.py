"""
Configuration management for Polymarket Weather Engine.
Loads environment variables and sets risk/execution parameters.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv
from models import ExecutionMode

# Load local environment file if present
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

@dataclass
class Config:
    # Execution Mode: "PAPER" or "LIVE"
    MODE: ExecutionMode = ExecutionMode(os.getenv("POLY_MODE", "PAPER").upper())

    # Live execution is opt-in; audit deployment stays paused.
    LIVE_TRADING_ENABLED: bool = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
    LIVE_ENTRIES_ENABLED: bool = os.getenv("LIVE_ENTRIES_ENABLED", "false").lower() == "true"
    MAX_TRADE_USDC: float = float(os.getenv("MAX_TRADE_USDC", "5.0"))

    # Paper Trading initial balance
    INITIAL_PAPER_CASH: float = float(os.getenv("INITIAL_PAPER_CASH", "1000.0"))
    PAPER_LEDGER_PATH: str = os.getenv("PAPER_LEDGER_PATH", os.path.join(os.path.dirname(__file__), "data", "paper_v2_ledger.json"))

    # Strategy & Edge Thresholds
    MIN_EDGE_THRESHOLD: float = float(os.getenv("MIN_EDGE_THRESHOLD", "0.05")) # 5% edge hurdle
    MIN_EV_THRESHOLD: float = float(os.getenv("MIN_EV_THRESHOLD", "0.05"))     # $0.05 EV / share
    KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.25"))         # Quarter-Kelly

    # Risk Controls & Exposure Caps
    MAX_CONTRACT_ALLOCATION: float = float(os.getenv("MAX_CONTRACT_ALLOCATION", "0.15"))  # 15% of portfolio
    MAX_CITY_ALLOCATION: float = float(os.getenv("MAX_CITY_ALLOCATION", "0.25"))          # 25% of portfolio
    MIN_CASH_RESERVE: float = float(os.getenv("MIN_CASH_RESERVE", "0.20"))                # 20% cash buffer
    MAX_SLIPPAGE: float = float(os.getenv("MAX_SLIPPAGE", "0.02"))

    # Weather Model Settings
    DEFAULT_ENSEMBLE_STD_F: float = float(os.getenv("ENSEMBLE_STD_F", "2.2")) # std dev in °F
    DEFAULT_ENSEMBLE_STD_C: float = float(os.getenv("ENSEMBLE_STD_C", "1.2")) # std dev in °C
    PEAK_OFFSET_F: float = float(os.getenv("PEAK_OFFSET_F", "0.6"))            # sub-hourly peak offset
    PEAK_OFFSET_C: float = float(os.getenv("PEAK_OFFSET_C", "0.35"))

    # Polymarket Live Credentials (Only needed for LIVE mode)
    POLY_PRIVATE_KEY: str = os.getenv("POLY_PRIVATE_KEY", "")
    POLY_FUNDER: str = os.getenv("POLY_FUNDER", "")
    POLY_SIGNATURE_TYPE: int = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))
    POLY_API_KEY: str = os.getenv("POLY_API_KEY", "")
    POLY_API_SECRET: str = os.getenv("POLY_API_SECRET", "")
    POLY_PASSPHRASE: str = os.getenv("POLY_PASSPHRASE", "")
    POLY_CHAIN_ID: int = int(os.getenv("POLY_CHAIN_ID", "137")) # Polygon mainnet

    # Proxy Configuration (ProtonVPN Iceland via wireproxy)
    PROXY_HTTP: str = os.getenv("PROXY_HTTP", "http://127.0.0.1:1081")
    PROXY_SOCKS5: str = os.getenv("PROXY_SOCKS5", "socks5h://127.0.0.1:1080")

    # Endpoints
    GAMMA_API_BASE: str = "https://gamma-api.polymarket.com"
    CLOB_API_BASE: str = "https://clob.polymarket.com"


# Global singleton config
cfg = Config()
