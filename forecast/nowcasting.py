"""
Real-time METAR Nowcasting & Microclimate Calibration Module.
Pulls live sub-hourly observations from NOAA / FAA AviationWeather.gov API.
Provides:
1. Microclimate and Station Metadata calibration.
2. Hard mathematical pruning: vetoes brackets whose temperature bounds have already been breached today.
3. Intraday trajectory and solar insolation adjustment (convective cloud / overcast dampening).
4. Redundant fallback to Open-Meteo current surface observations if AviationWeather is unreachable.
"""
import time
import json
import logging
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple, Any
from zoneinfo import ZoneInfo

from models import WeatherContract, Bracket, MetricType, UnitType
from registry.stations import StationMetadata, resolve_station

logger = logging.getLogger("MetarNowcaster")


@dataclass
class MetarRecord:
    icao: str
    report_time: datetime
    temp_c: float
    dewp_c: Optional[float] = None
    wind_spd_kt: Optional[float] = None
    cloud_cover: str = "CLR"  # CLR, FEW, SCT, BKN, OVC
    raw_text: str = ""


@dataclass
class StationNowcast:
    station_icao: str
    station_name: str
    city: str
    target_date: str
    is_today: bool
    local_time_str: str
    latest_temp_c: Optional[float] = None
    latest_temp_f: Optional[float] = None
    today_max_c: Optional[float] = None
    today_max_f: Optional[float] = None
    today_min_c: Optional[float] = None
    today_min_f: Optional[float] = None
    latest_obs_time: Optional[datetime] = None
    cloud_cover: str = "CLR"
    is_overcast: bool = False
    solar_dampening_c: float = 0.0
    observations_count: int = 0
    source: str = "AviationWeather-METAR"


class MetarNowcaster:
    """
    Manages live METAR data retrieval, in-memory caching, and nowcasting assessments.
    """
    def __init__(self, cache_ttl_seconds: int = 300, request_timeout: int = 6):
        self.cache_ttl = cache_ttl_seconds
        self.timeout = request_timeout
        # Cache key: (icao, target_date) -> (timestamp, StationNowcast)
        self._cache: Dict[Tuple[str, str], Tuple[float, StationNowcast]] = {}

    def fetch_station_nowcast(
        self,
        station: StationMetadata,
        target_date: str,
        force_refresh: bool = False
    ) -> Optional[StationNowcast]:
        """
        Fetches live METAR reports for a station and returns a StationNowcast summary.
        """
        cache_key = (station.effective_metar_icao, target_date)
        now = time.time()
        if not force_refresh and cache_key in self._cache:
            cached_time, cached_nowcast = self._cache[cache_key]
            if now - cached_time < self.cache_ttl:
                return cached_nowcast

        nowcast = self._fetch_from_aviation_weather(station, target_date)
        if not nowcast:
            nowcast = self._fetch_from_open_meteo_fallback(station, target_date)

        if nowcast:
            self._cache[cache_key] = (now, nowcast)

        return nowcast

    def _fetch_from_aviation_weather(
        self,
        station: StationMetadata,
        target_date: str
    ) -> Optional[StationNowcast]:
        """Fetches up to 24 hours of METAR observations from aviationweather.gov."""
        icao = station.effective_metar_icao
        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&hours=24&format=json"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "PolymarketWeatherIntelligence/1.0"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not isinstance(data, list) or not data:
                return None

            try:
                stn_tz = ZoneInfo(station.timezone)
            except Exception:
                stn_tz = timezone.utc

            now_local = datetime.now(stn_tz)
            is_today = (target_date == now_local.strftime("%Y-%m-%d"))

            today_temps: List[float] = []
            latest_rec: Optional[Dict[str, Any]] = None
            latest_dt: Optional[datetime] = None
            cloud_cover = "CLR"
            is_overcast = False

            for item in data:
                t_val = item.get("temp")
                rep_time_str = item.get("reportTime")
                if t_val is None or not rep_time_str:
                    continue

                try:
                    dt_utc = datetime.fromisoformat(rep_time_str.replace("Z", "+00:00"))
                except Exception:
                    continue

                dt_local = dt_utc.astimezone(stn_tz)

                # Check if observation belongs to target_date
                if dt_local.strftime("%Y-%m-%d") == target_date:
                    today_temps.append(float(t_val))

                if latest_dt is None or dt_utc > latest_dt:
                    latest_dt = dt_utc
                    latest_rec = item

            if not latest_rec and not today_temps:
                return None

            latest_temp_c = float(latest_rec.get("temp")) if latest_rec and latest_rec.get("temp") is not None else None
            if latest_temp_c is None and today_temps:
                latest_temp_c = today_temps[-1]

            clouds = latest_rec.get("clouds", []) if latest_rec else []
            for c in clouds:
                cover = c.get("cover", "")
                if cover in ["OVC", "BKN"]:
                    cloud_cover = cover
                    is_overcast = True
                    break
                elif cover in ["SCT", "FEW"]:
                    cloud_cover = cover

            # Daytime solar insolation dampening
            # If broken or overcast during peak heating hours (10:00 - 15:00 local)
            solar_dampening_c = 0.0
            if is_today and is_overcast and (10 <= now_local.hour <= 15):
                solar_dampening_c = 0.8 if cloud_cover == "BKN" else 1.4

            today_max_c = max(today_temps) if today_temps else latest_temp_c
            today_min_c = min(today_temps) if today_temps else latest_temp_c

            def to_f(c):
                return round(c * 9.0 / 5.0 + 32.0, 2) if c is not None else None

            return StationNowcast(
                station_icao=station.icao,
                station_name=station.name,
                city=station.city,
                target_date=target_date,
                is_today=is_today,
                local_time_str=now_local.strftime("%Y-%m-%d %H:%M %Z"),
                latest_temp_c=latest_temp_c,
                latest_temp_f=to_f(latest_temp_c),
                today_max_c=today_max_c,
                today_max_f=to_f(today_max_c),
                today_min_c=today_min_c,
                today_min_f=to_f(today_min_c),
                latest_obs_time=latest_dt,
                cloud_cover=cloud_cover,
                is_overcast=is_overcast,
                solar_dampening_c=solar_dampening_c,
                observations_count=len(today_temps),
                source="AviationWeather-METAR"
            )
        except Exception as e:
            logger.debug(f"AviationWeather fetch failed for {station.icao}: {e}")
            return None

    def _fetch_from_open_meteo_fallback(
        self,
        station: StationMetadata,
        target_date: str
    ) -> Optional[StationNowcast]:
        """Fallback to Open-Meteo current weather endpoint."""
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={station.lat}&longitude={station.lon}"
            f"&current=temperature_2m,cloud_cover"
            f"&timezone={station.timezone}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PolymarketWeatherIntelligence/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            current = data.get("current", {})
            temp_c = current.get("temperature_2m")
            if temp_c is None:
                return None

            try:
                stn_tz = ZoneInfo(station.timezone)
            except Exception:
                stn_tz = timezone.utc

            now_local = datetime.now(stn_tz)
            is_today = (target_date == now_local.strftime("%Y-%m-%d"))

            cloud_pct = current.get("cloud_cover", 0)
            cloud_cover = "OVC" if cloud_pct > 80 else ("BKN" if cloud_pct > 50 else ("SCT" if cloud_pct > 25 else "CLR"))
            is_overcast = cloud_pct > 50

            solar_dampening_c = 0.0
            if is_today and is_overcast and (10 <= now_local.hour <= 15):
                solar_dampening_c = 0.6 if cloud_pct < 80 else 1.2

            def to_f(c):
                return round(c * 9.0 / 5.0 + 32.0, 2) if c is not None else None

            return StationNowcast(
                station_icao=station.icao,
                station_name=station.name,
                city=station.city,
                target_date=target_date,
                is_today=is_today,
                local_time_str=now_local.strftime("%Y-%m-%d %H:%M %Z"),
                latest_temp_c=float(temp_c),
                latest_temp_f=to_f(float(temp_c)),
                today_max_c=float(temp_c),
                today_max_f=to_f(float(temp_c)),
                today_min_c=float(temp_c),
                today_min_f=to_f(float(temp_c)),
                latest_obs_time=datetime.now(timezone.utc),
                cloud_cover=cloud_cover,
                is_overcast=is_overcast,
                solar_dampening_c=solar_dampening_c,
                observations_count=1,
                source="OpenMeteo-Fallback"
            )
        except Exception as e:
            logger.debug(f"Open-Meteo fallback failed for {station.icao}: {e}")
            return None

    @staticmethod
    def evaluate_bracket_validity(
        contract: WeatherContract,
        bracket: Bracket,
        nowcast: Optional[StationNowcast]
    ) -> Tuple[bool, str]:
        """
        Hard Mathematical Veto:
        Checks if the bracket bounds have already been physically exceeded by recorded observations today.
        """
        if not nowcast or not nowcast.is_today:
            return True, "OK"

        is_f = (contract.unit == UnitType.FAHRENHEIT)

        # 1. T_MAX: Daily Maximum Temperature
        if contract.metric == MetricType.T_MAX and nowcast.today_max_c is not None:
            today_max = nowcast.today_max_f if is_f else nowcast.today_max_c
            # If today's observed max is strictly greater than the bracket's upper bound
            # Then this bracket can NEVER win (the daily maximum is already higher).
            if today_max > bracket.max_temp:
                return False, (
                    f"METAR Veto: Recorded max today ({today_max:.1f}°{contract.unit.value}) "
                    f"already exceeded bracket ceiling ({bracket.max_temp:.1f}°{contract.unit.value})"
                )

        # 2. T_MIN: Daily Minimum Temperature
        elif contract.metric == MetricType.T_MIN and nowcast.today_min_c is not None:
            today_min = nowcast.today_min_f if is_f else nowcast.today_min_c
            # If today's observed min is strictly lower than the bracket's lower bound
            # Then this bracket can NEVER win (the daily minimum is already lower).
            if today_min < bracket.min_temp:
                return False, (
                    f"METAR Veto: Recorded min today ({today_min:.1f}°{contract.unit.value}) "
                    f"already dropped below bracket floor ({bracket.min_temp:.1f}°{contract.unit.value})"
                )

        return True, "OK"
