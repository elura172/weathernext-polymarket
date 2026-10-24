"""
Base Weather Provider Interface.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from models import HourlyForecast, UnitType

class WeatherProvider(ABC):
    @abstractmethod
    def get_hourly_forecast(
        self,
        station_icao: str,
        lat: float,
        lon: float,
        target_date: str,
        unit: UnitType
    ) -> Optional[HourlyForecast]:
        """Fetch 24-hour hourly temperatures for the target date."""
        pass
