"""
Calibrator for converting discrete hourly forecast series into analog sensor extremes.
Compensates for sub-hourly peak heating, station microclimates (UHI, coastal marine layers),
and real-time METAR nowcast trajectories.
"""
from typing import Optional
from models import MetricType, UnitType, HourlyForecast
from registry.stations import StationMetadata
from forecast.nowcasting import StationNowcast
from config import cfg

class ForecastCalibrator:
    @staticmethod
    def calibrate_target_distribution(
        forecast: HourlyForecast,
        metric: MetricType,
        unit: UnitType,
        station: Optional[StationMetadata] = None,
        nowcast: Optional[StationNowcast] = None
    ):
        """
        Calculates expected peak/trough mean (mu) and ensemble standard deviation (sigma).
        Accounts for:
        1. Sub-hourly instantaneous peak/trough sensor sampling vs discrete hourly steps.
        2. Station-specific microclimatic bias (Urban Heat Island, airport tarmac, coastal sea breezes).
        3. Real-time METAR nowcast trajectory, convective cloud dampening, and collapsed daytime sigma.
        """
        peak_offset = cfg.PEAK_OFFSET_F if unit == UnitType.FAHRENHEIT else cfg.PEAK_OFFSET_C
        is_f = (unit == UnitType.FAHRENHEIT)

        # 1. Base Peak/Trough Offset
        if metric == MetricType.T_MAX:
            mu = forecast.t_max + peak_offset
        else:
            mu = forecast.t_min - peak_offset

        sigma = max(0.5, forecast.ensemble_std)

        # 2. Station Microclimate Adjustment
        if station and station.microclimate_bias_c != 0.0:
            bias = station.microclimate_bias_c * 1.8 if is_f else station.microclimate_bias_c
            if metric == MetricType.T_MAX:
                mu += bias
            else:
                # Nighttime minimums retain thermal mass in urban heat islands
                mu += (bias * 0.7)

        # 3. METAR Nowcasting & Intraday Trajectory Corrections
        if nowcast and nowcast.is_today:
            # A. Solar insolation dampening from convective cloud cover (OVC / BKN)
            if metric == MetricType.T_MAX and nowcast.solar_dampening_c > 0.0:
                damp = nowcast.solar_dampening_c * 1.8 if is_f else nowcast.solar_dampening_c
                mu -= damp

            # B. Physical floor constraint: Daily max cannot be lower than already recorded max today
            if metric == MetricType.T_MAX:
                today_max = nowcast.today_max_f if is_f else nowcast.today_max_c
                if today_max is not None:
                    mu = max(mu, today_max)

            # C. Physical ceiling constraint: Daily min cannot be higher than already recorded min today
            elif metric == MetricType.T_MIN:
                today_min = nowcast.today_min_f if is_f else nowcast.today_min_c
                if today_min is not None:
                    mu = min(mu, today_min)

            # D. Uncertainty collapse as the target day's peak window elapses
            # If several METAR reports have already been observed today
            if nowcast.observations_count >= 10:
                sigma = max(0.3, sigma * 0.65)

        return mu, sigma

