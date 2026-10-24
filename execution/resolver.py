"""
Oracle Settlement & Position Resolution Engine.
Fetches ground-truth station observations (NOAA / METAR) for completed events,
identifies winning brackets, redeems winning tokens at $1.00, and finalizes realized PnL.
"""
import requests
import logging
from datetime import datetime, date
from typing import Dict, Any, Optional, Tuple
from models import WeatherContract, MetricType, UnitType
from registry.stations import resolve_station

logger = logging.getLogger(__name__)

class OracleResolver:
    """
    Scrapes and verifies actual recorded high/low temperatures for completed observation dates.
    """
    @staticmethod
    def fetch_station_recorded_extreme(
        station_icao: str,
        lat: float,
        lon: float,
        obs_date: str,
        metric: MetricType,
        unit: UnitType
    ) -> Optional[float]:
        """
        Retrieves actual recorded extreme temperature for the station on obs_date.
        Uses NOAA / Open-Meteo archive observation feeds.
        """
        unit_param = "fahrenheit" if unit == UnitType.FAHRENHEIT else "celsius"
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": obs_date,
            "end_date": obs_date,
            "daily": "temperature_2m_max" if metric == MetricType.T_MAX else "temperature_2m_min",
            "temperature_unit": unit_param,
            "timezone": "auto"
        }
        try:
            resp = requests.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                daily = data.get("daily", {})
                key = "temperature_2m_max" if metric == MetricType.T_MAX else "temperature_2m_min"
                values = daily.get(key, [])
                if values and values[0] is not None:
                    # Stations report rounded whole degrees for US/NOAA
                    raw_val = float(values[0])
                    return round(raw_val)
        except Exception as e:
            logger.debug(f"Failed archive query for {station_icao}: {e}")

        # Fallback to forecast API past-day observation
        try:
            url_fc = "https://api.open-meteo.com/v1/forecast"
            params_fc = {
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max" if metric == MetricType.T_MAX else "temperature_2m_min",
                "temperature_unit": unit_param,
                "past_days": 2,
                "forecast_days": 1,
                "timezone": "auto"
            }
            resp = requests.get(url_fc, params=params_fc, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                daily = data.get("daily", {})
                dates = daily.get("time", [])
                key = "temperature_2m_max" if metric == MetricType.T_MAX else "temperature_2m_min"
                values = daily.get(key, [])
                for d_str, val in zip(dates, values):
                    if d_str == obs_date and val is not None:
                        return round(float(val))
        except Exception as e:
            logger.error(f"Error fetching recorded observation for {station_icao}: {e}")

        return None

    @staticmethod
    def resolve_contract_outcome(
        contract_title: str,
        bracket_label: str,
        target_date: Optional[str] = None
    ) -> Tuple[Optional[bool], Optional[float], Optional[Tuple[float, float]]]:
        """
        Determines whether bracket_label won or lost based on recorded station observations.
        Returns: (is_winner, recorded_temp, (min_bound, max_bound))
        """
        from polymarket.parser import parse_date_from_text, parse_bracket_bounds

        station = resolve_station(contract_title)
        if not station:
            logger.warning(f"OracleResolver: could not resolve station for title: {contract_title}")
            return None, None, None

        metric = MetricType.T_MIN if any(k in contract_title.lower() for k in ["lowest", "low temp", "min"]) else MetricType.T_MAX
        unit = UnitType.FAHRENHEIT if ("°f" in contract_title.lower() or "°f" in bracket_label.lower() or station.default_unit == "F") else UnitType.CELSIUS

        if not target_date:
            target_date = parse_date_from_text(contract_title)
        if not target_date:
            return None, None, None

        # If bracket_label is "Yes" or "No", the temperature specification is in contract_title
        bound_text = contract_title if bracket_label.strip().lower() in ["yes", "no"] else bracket_label
        min_b, max_b, _ = parse_bracket_bounds(bound_text, unit, station.precision)

        recorded = OracleResolver.fetch_station_recorded_extreme(
            station.icao, station.lat, station.lon, target_date, metric, unit
        )
        if recorded is None:
            logger.info(f"OracleResolver: observation for {station.icao} on {target_date} not yet available.")
            return None, None, None

        in_range = (min_b <= recorded <= max_b)
        is_winner = (not in_range) if bracket_label.strip().lower() == "no" else in_range

        logger.info(
            f"OracleResolver: {contract_title} [{bracket_label}] -> Recorded: {recorded}°{unit.value}, "
            f"Bounds: [{min_b}, {max_b}], Winner: {is_winner}"
        )
        return is_winner, recorded, (min_b, max_b)
