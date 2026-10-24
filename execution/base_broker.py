"""
Base Broker Interface for trade execution and portfolio queries.
"""
from abc import ABC, abstractmethod
from typing import List
from models import TradeSignal, PortfolioState

class BaseBroker(ABC):
    @abstractmethod
    def get_portfolio_state(self) -> PortfolioState:
        pass

    @abstractmethod
    def execute_signals(self, signals: List[TradeSignal]) -> List[dict]:
        pass
