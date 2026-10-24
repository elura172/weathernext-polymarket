"""
High-Resolution Public Fallback Weather Provider (ECMWF IFS / HRRR via Open-Meteo).
Zero-credential, live, real-time hourly meteorological forecasts.
"""
import requests
import math
import logging
from datetime import datetime
from typing import Optional, List
from models import HourlyForecast, UnitType
from forecast.base import WeatherProvider
from config import cfg

logger = logging.getLogger(__name__)

class PublicFallbackProvider(WeatherProvider):
    """
    Queries high-resolution hourly forecast for the exact target date and coordinates.
    """
    def __init__(self, base_url: str = "https://api.open-meteo.com/v1/forecast"):
        self.base_url = base_url

    def get_hourly_forecast(
        self,
        station_icao: str,
        lat: float,
        lon: float,
        target_date: str,
        unit: UnitType
    ) -> Optional[HourlyForecast]:
        unit_param = "fahrenheit" if unit == UnitType.FAHRENHEIT else "celsius"
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m",
            "temperature_unit": unit_param,
            "start_date": target_date,
            "end_date": target_date,
            "timezone": "auto"
        }
        try:
            resp = requests.get(self.base_url, params=params, timeout=8)
            if resp.status_code != 200:
                params.pop("start_date", None)
                params.pop("end_date", None)
                params["forecast_days"] = 7
                resp = requests.get(self.base_url, params=params, timeout=8)

            resp.raise_for_status()
            data = resp.json()
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])

            filtered_ts: List[datetime] = []
            filtered_temps: List[float] = []

            for t_str, temp in zip(times, temps):
                if temp is None or not math.isfinite(float(temp)):
                    continue
                if t_str.startswith(target_date):
                    filtered_ts.append(datetime.fromisoformat(t_str))
                    filtered_temps.append(float(temp))

            if len(set(filtered_ts)) < 23:
                logger.warning("Incomplete forecast for %s on %s; skipping", station_icao, target_date)
                return None

            std_dev = cfg.DEFAULT_ENSEMBLE_STD_F if unit == UnitType.FAHRENHEIT else cfg.DEFAULT_ENSEMBLE_STD_C
            return HourlyForecast(
                station_icao=station_icao,
                target_date=target_date,
                timestamps=filtered_ts,
                temperatures=filtered_temps,
                t_max=max(filtered_temps),
                t_min=min(filtered_temps),
                ensemble_std=std_dev,
                source_model="OpenMeteo-point-forecast-fixed-sigma"
            )
        except Exception as e:
            logger.error(f"Error querying Open-Meteo for {station_icao}: {e}")
            return None
