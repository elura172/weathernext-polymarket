"""
Google DeepMind WeatherNext 3 Forecast Provider.
Interfaces with Google Earth Engine / Google Cloud Storage when allowlisted.
"""
import logging
from datetime import datetime
from typing import Optional, List
from models import HourlyForecast, UnitType
from forecast.base import WeatherProvider
from config import cfg

logger = logging.getLogger(__name__)

class WeatherNextProvider(WeatherProvider):
    """
    Google DeepMind WeatherNext 3 Provider.
    Extracts 5km hourly surface temperature and ensemble spread.
    """
    def __init__(self, ee_project_id: Optional[str] = None):
        self.ee_project_id = ee_project_id
        self.initialized = False
        self._init_earth_engine()

    def _init_earth_engine(self):
        try:
            import ee
            if self.ee_project_id:
                ee.Initialize(project=self.ee_project_id)
            else:
                ee.Initialize()
            self.initialized = True
            logger.info("Successfully initialized Earth Engine for WeatherNext 3")
        except Exception as e:
            logger.warning(
                f"WeatherNext 3 Earth Engine access not initialized ({e}). "
                "Ensure your Google Account is allowlisted via the WeatherNext Data Request Form."
            )
            self.initialized = False

    def get_hourly_forecast(
        self,
        station_icao: str,
        lat: float,
        lon: float,
        target_date: str,
        unit: UnitType
    ) -> Optional[HourlyForecast]:
        if not self.initialized:
            return None

        try:
            import ee
            # Query Earth Engine WeatherNext 3 collection
            point = ee.Geometry.Point([lon, lat])
            dataset = ee.ImageCollection("GOOGLE/DEEPMIND/WEATHERNEXT_3/HOURLY") \
                .filterDate(f"{target_date}T00:00:00", f"{target_date}T23:59:59") \
                .filterBounds(point)

            # Extract 2-meter temperature bands
            temps_kelvin = dataset.select("temperature_2m").getRegion(point, 5000).getInfo()
            # Parse time-series
            timestamps: List[datetime] = []
            temps: List[float] = []
            header = temps_kelvin[0]
            val_idx = header.index("temperature_2m")
            time_idx = header.index("time")

            for row in temps_kelvin[1:]:
                ts = datetime.utcfromtimestamp(row[time_idx] / 1000.0)
                k_val = row[val_idx]
                if k_val is not None:
                    # Convert Kelvin to target unit
                    if unit == UnitType.FAHRENHEIT:
                        val = (k_val - 273.15) * 9.0 / 5.0 + 32.0
                    else:
                        val = k_val - 273.15
                    timestamps.append(ts)
                    temps.append(val)

            if not temps:
                return None

            std_dev = cfg.DEFAULT_ENSEMBLE_STD_F if unit == UnitType.FAHRENHEIT else cfg.DEFAULT_ENSEMBLE_STD_C
            return HourlyForecast(
                station_icao=station_icao,
                target_date=target_date,
                timestamps=timestamps,
                temperatures=temps,
                t_max=max(temps),
                t_min=min(temps),
                ensemble_std=std_dev,
                source_model="WeatherNext3"
            )
        except Exception as e:
            logger.error(f"Failed to query WeatherNext 3: {e}")
            return None
