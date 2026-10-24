"""
Unit tests for METAR Nowcasting & Station Microclimate Calibration.
"""
from datetime import datetime, timezone
from models import WeatherContract, Bracket, HourlyForecast, MetricType, UnitType
from registry.stations import resolve_station, STATION_CATALOG
from forecast.nowcasting import MetarNowcaster, StationNowcast
from forecast.calibrator import ForecastCalibrator
from strategy.pricer import BracketPricer


def test_station_microclimate_metadata():
    nyc = resolve_station("knyc")
    assert nyc is not None
    assert nyc.station_type == "urban_park"
    assert nyc.microclimate_bias_c == 0.6
    assert nyc.effective_metar_icao == "KNYC"

    sfo = resolve_station("ksfo")
    assert sfo is not None
    assert sfo.microclimate_bias_c == -0.8
    assert sfo.station_type == "coastal_airport"


def test_hard_bracket_veto_tmax():
    contract = WeatherContract(
        event_id="e1",
        event_title="Highest temp in Dallas",
        event_slug="highest-temp-dallas",
        city="Dallas",
        station_icao="kdal",
        station_name="Love Field",
        lat=32.84,
        lon=-96.85,
        timezone="America/Chicago",
        metric=MetricType.T_MAX,
        unit=UnitType.FAHRENHEIT,
        target_date="2026-09-04",
        resolution_source_url="",
        precision=1.0,
    )
    b_dead = Bracket("1", "c1", "t1", "t2", "80°F or below", float("-inf"), 80.5, 0.1, 0.9)
    b_live = Bracket("2", "c2", "t3", "t4", "85°F", 84.5, 85.5, 0.3, 0.7)

    # Simulated nowcast showing Dallas already recorded 83.0°F today
    nowcast = StationNowcast(
        station_icao="kdal",
        station_name="Dallas Love Field",
        city="Dallas",
        target_date="2026-09-04",
        is_today=True,
        local_time_str="2026-09-04 14:00 CDT",
        latest_temp_c=28.3,
        latest_temp_f=83.0,
        today_max_c=28.3,
        today_max_f=83.0,
        today_min_c=20.0,
        today_min_f=68.0,
    )

    valid_dead, reason_dead = MetarNowcaster.evaluate_bracket_validity(contract, b_dead, nowcast)
    assert not valid_dead
    assert "exceeded bracket ceiling" in reason_dead

    valid_live, reason_live = MetarNowcaster.evaluate_bracket_validity(contract, b_live, nowcast)
    assert valid_live
    assert reason_live == "OK"


def test_forecast_calibrator_microclimate_and_dampening():
    forecast = HourlyForecast(
        station_icao="knyc",
        target_date="2026-09-04",
        timestamps=[datetime.now(timezone.utc)],
        temperatures=[75.0],
        t_max=75.0,
        t_min=60.0,
        ensemble_std=1.5,
        source_model="Test"
    )
    stn_nyc = resolve_station("knyc")

    # Base calibration without station/nowcast
    mu_base, sigma_base = ForecastCalibrator.calibrate_target_distribution(
        forecast, MetricType.T_MAX, UnitType.FAHRENHEIT
    )

    # Calibration with NYC UHI microclimate (+0.6°C = +1.08°F)
    mu_stn, sigma_stn = ForecastCalibrator.calibrate_target_distribution(
        forecast, MetricType.T_MAX, UnitType.FAHRENHEIT, station=stn_nyc
    )
    assert mu_stn > mu_base
    assert abs((mu_stn - mu_base) - (0.6 * 1.8)) < 1e-4

    # Nowcast with overcast convective solar dampening (solar_dampening_c = 1.0°C = 1.8°F)
    nowcast = StationNowcast(
        station_icao="knyc",
        station_name="NYC Central Park",
        city="New York",
        target_date="2026-09-04",
        is_today=True,
        local_time_str="2026-09-04 13:00 EDT",
        latest_temp_c=22.0,
        latest_temp_f=71.6,
        today_max_c=22.0,
        today_max_f=71.6,
        today_min_c=18.0,
        today_min_f=64.4,
        is_overcast=True,
        solar_dampening_c=1.0,
    )
    mu_damp, _ = ForecastCalibrator.calibrate_target_distribution(
        forecast, MetricType.T_MAX, UnitType.FAHRENHEIT, station=stn_nyc, nowcast=nowcast
    )
    assert mu_damp < mu_stn


def test_bracket_pricer_with_nowcast_veto_and_normalization():
    contract = WeatherContract(
        event_id="e1",
        event_title="Highest temp in Hong Kong",
        event_slug="hk-temp",
        city="Hong Kong",
        station_icao="vhhh",
        station_name="Hong Kong Observatory",
        lat=22.3,
        lon=114.17,
        timezone="Asia/Hong_Kong",
        metric=MetricType.T_MAX,
        unit=UnitType.CELSIUS,
        target_date="2026-09-04",
        resolution_source_url="",
        precision=1.0,
        brackets=[
            Bracket("1", "c1", "t1", "t2", "28°C or below", float("-inf"), 28.5, 0.1, 0.9),
            Bracket("2", "c2", "t3", "t4", "29°C", 28.5, 29.5, 0.2, 0.8),
            Bracket("3", "c3", "t5", "t6", "30°C", 29.5, 30.5, 0.4, 0.6),
            Bracket("4", "c4", "t7", "t8", "31°C or higher", 30.5, float("inf"), 0.3, 0.7),
        ]
    )
    forecast = HourlyForecast(
        station_icao="vhhh",
        target_date="2026-09-04",
        timestamps=[datetime.now(timezone.utc)],
        temperatures=[29.0],
        t_max=29.2,
        t_min=25.0,
        ensemble_std=1.0,
        source_model="Test"
    )

    # HK observed 30.0°C today -> brackets <= 29.5°C must be vetoed
    nowcast = StationNowcast(
        station_icao="vhhh",
        station_name="Hong Kong Observatory",
        city="Hong Kong",
        target_date="2026-09-04",
        is_today=True,
        local_time_str="2026-09-04 15:30 HKT",
        latest_temp_c=30.0,
        latest_temp_f=86.0,
        today_max_c=30.0,
        today_max_f=86.0,
        today_min_c=27.0,
        today_min_f=80.6,
        observations_count=12,
    )

    priced = BracketPricer.price_contract_brackets(contract, forecast, nowcast=nowcast)

    # Brackets 1 and 2 must have model_prob == 0.0 because max_temp < 30.0°C
    assert priced[0].model_prob == 0.0
    assert priced[0].veto_reason is not None
    assert priced[1].model_prob == 0.0
    assert priced[1].veto_reason is not None

    # Total remaining probabilities must sum to 1.0
    total_p = sum(b.model_prob for b in priced)
    assert abs(total_p - 1.0) < 1e-4
